#!flask/bin/python
import lib.docker_config as config
from lib import sensory_interface
from flask import Flask, jsonify, request, make_response, abort
from flask_cors import CORS, cross_origin
import base64
import logging
import json
from datetime import datetime
import os
import errno
import uuid
import numpy
import pika


# Setup logging.
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S %p',
    level=logging.DEBUG,
    filemode='w',
    filename="%s/sensoryservice.log" % config.LOGS_DIR
)

# Generate our Sensory Service Interface
ssc = sensory_interface.SensoryInterface('server')

# https://stackoverflow.com/questions/273192/how-can-i-create-a-directory-if-it-does-not-exist
def make_sure_path_exists(path):
    try:
        os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise


def sensory_store(data_dir, data_category, raw_image_data):
    filename = "%s" % datetime.now().strftime('%Y-%m-%d_%H_%M_%S_%f.tmp.png')
    path = "%s%s/" % (data_dir, data_category)
    full_filename = "%s%s" % (path, filename)
    logging.debug("(%s)" % (full_filename))
    make_sure_path_exists(path)
    with open(full_filename, 'wb') as f:
        f.write(raw_image_data)
    return True


def sensory_request(batch_size, noise=0):
    data, labels = ssc.get_batch(batch_size, noise)
    return data, labels


def sensory_batch_request(batch_size, noise=0):
    sensory_batch_request_id = uuid.uuid4()

    # determine how many shards need to be created for the batch
    shards = 1
    tail_shard_size = 0
    if batch_size > config.SENSORY_SERVICE_SHARD_SIZE:
        tail_shard_size = batch_size % config.SENSORY_SERVICE_SHARD_SIZE
        shards = (batch_size - (batch_size % config.SENSORY_SERVICE_SHARD_SIZE))/config.SENSORY_SERVICE_SHARD_SIZE

    try:
        ## Submit our message
        url = config.SENSORY_SERVICE_RABBITMQ_URL
        # logging.debug(url)
        parameters = pika.URLParameters(url)
        connection = pika.BlockingConnection(parameters=parameters)

        channel = connection.channel()

        channel.queue_declare(queue=config.SENSORY_SERVICE_RABBITMQ_BATCH_REQUEST_TASK_QUEUE, durable=True)

        sensory_request = {}
        sensory_request['sensory_batch_request_id'] = str(sensory_batch_request_id)
        if batch_size > config.SENSORY_SERVICE_SHARD_SIZE:
            sensory_request['batch_size'] = config.SENSORY_SERVICE_SHARD_SIZE
        else:
            sensory_request['batch_size'] = batch_size
        sensory_request['noise'] = noise

        for shard in range(0, shards):
            # send message
            channel.basic_publish(exchange=config.SENSORY_SERVICE_RABBITMQ_EXCHANGE,
                                  routing_key=config.SENSORY_SERVICE_RABBITMQ_BATCH_REQUEST_ROUTING_KEY,
                                  body=json.dumps(sensory_request),
                                  properties=pika.BasicProperties(
                                      delivery_mode=2,  # make message persistent
                                  ))
            logging.debug(" [x] Sent %r" % json.dumps(sensory_request))
        if tail_shard_size > 0:
            # send final message of size tail_shard_size
            sensory_request['batch_size'] = tail_shard_size
            channel.basic_publish(exchange=config.SENSORY_SERVICE_RABBITMQ_EXCHANGE,
                                  routing_key=config.SENSORY_SERVICE_RABBITMQ_BATCH_REQUEST_ROUTING_KEY,
                                  body=json.dumps(sensory_request),
                                  properties=pika.BasicProperties(
                                      delivery_mode=2,  # make message persistent
                                  ))
            logging.debug(" [x] Sent %r" % json.dumps(sensory_request))
        connection.close()
    except:
        # something went wrong..
        logging.error('we had a failure sending the batch requests to the message system')
        return None
    return sensory_batch_request_id


# return a queued batch order message for the supplied request id if possible
def sensory_batch_poll(batch_id):
    # lets try to grab more than one at a time // combine and return
    # since this is going to clients lets reduce chatter

    data = None
    label = None

    url = config.SENSORY_SERVICE_RABBITMQ_URL
    # logging.debug(url)
    parameters = pika.URLParameters(url)
    connection = pika.BlockingConnection(parameters=parameters)

    channel = connection.channel()

    method_frame, header_frame, body = channel.basic_get(batch_id)
    if method_frame:
        logging.debug("%s %s %s" % (method_frame, header_frame, body))
        message = json.loads(body)
        label = message['label']
        data = message['data']
        logging.debug(label)
        logging.debug(data)
        channel.basic_ack(method_frame.delivery_tag)
    else:
        logging.debug('no message returned')
    connection.close()
    return data, label


app = Flask(__name__)
cors = CORS(app, resources={r"/api/*": {"origins": "http://localhost:*"}})


@app.route('/api/sensory/store', methods=['POST'])
def make_api_sensory_store_public():
    if request.headers['API-ACCESS-KEY'] != config.API_ACCESS_KEY:
        abort(401)
    if request.headers['API-VERSION'] != config.API_VERSION:
        abort(400)
    if not request.json:
        abort(400)

    if 'name' not in request.json:
        abort(400)
    if 'width' not in request.json:
        abort(400)
    if 'height' not in request.json:
        abort(400)
    if 'category' not in request.json:
        abort(400)
    if 'data' not in request.json:
        abort(400)
    if 'data' in request.json and type(request.json['data']) != unicode:
        abort(400)

    dataset_name = request.json.get('name')
    image_width = request.json.get('width')
    image_height = request.json.get('height')
    category = request.json.get('category')
    encoded_image_data = request.json.get('data')
    decoded_image_data = base64.b64decode(encoded_image_data)

    network_name = "%s_%ix%i" % (dataset_name, image_width, image_height)
    data_directory = "%s/%s/data/" % (config.DATA_BASE_DIRECTORY, network_name)

    return_code = sensory_store(data_directory, category, decoded_image_data)
    return make_response(jsonify({'sensory_store': return_code}), 201)


# for big batches
@app.route('/api/sensory/batch', methods=['POST'])
def make_api_sensory_batch_request_public():
    if request.headers['API-ACCESS-KEY'] != config.API_ACCESS_KEY:
        logging.debug('bad access key')
        abort(401)
    if request.headers['API-VERSION'] != config.API_VERSION:
        logging.debug('bad access version')
        abort(400)
    if not request.json:
        logging.debug('request not json')
        abort(400)

    if 'batch_size' not in request.json:
        logging.debug('batch size not in request')
        abort(400)
    if 'noise' not in request.json:
        logging.debug('noise not in request')
        abort(400)

    batch_size = request.json.get('batch_size')
    noise = request.json.get('noise')

    sensory_batch_request_id = sensory_batch_request(batch_size, noise)
    return make_response(jsonify({'batch_id': sensory_batch_request_id}), 201)


@app.route('/api/sensory/poll', methods=['POST'])
def make_api_sensory_poll_public():
    if request.headers['API-ACCESS-KEY'] != config.API_ACCESS_KEY:
        logging.debug('bad access key')
        abort(401)
    if request.headers['API-VERSION'] != config.API_VERSION:
        logging.debug('bad access version')
        abort(400)
    if not request.json:
        logging.debug('request not json')
        abort(400)

    if 'batch_id' not in request.json:
        logging.debug('batch id not in request')
        abort(400)

    batch_id = request.json.get('batch_id')

    data, label = sensory_batch_poll(batch_id)
    return make_response(jsonify({
        'label': numpy.array(label).tolist(),
        'data': numpy.array(data).tolist()
    }), 201)


# for small batches..
@app.route('/api/sensory/request', methods=['POST'])
def make_api_sensory_request_public():
    if request.headers['API-ACCESS-KEY'] != config.API_ACCESS_KEY:
        logging.debug('bad access key')
        abort(401)
    if request.headers['API-VERSION'] != config.API_VERSION:
        logging.debug('bad access version')
        abort(400)
    if not request.json:
        logging.debug('request not json')
        abort(400)

    if 'batch_size' not in request.json:
        logging.debug('batch size not in request')
        abort(400)
    if 'noise' not in request.json:
        logging.debug('noise not in request')
        abort(400)

    batch_size = request.json.get('batch_size')
    noise = request.json.get('noise')

    data, labels = sensory_request(batch_size, noise)
    return make_response(jsonify({
                                  'labels': numpy.array(labels).tolist(),
        'data': numpy.array(data).tolist()
                                  }), 201)



@app.route('/api/version', methods=['GET'])
def make_api_version_public():
    return make_response(jsonify({'version':  str(config.API_VERSION)}), 201)


@app.route('/health/plain', methods=['GET'])
@cross_origin()
def make_health_plain_public():
    return make_response('true', 201)


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)


if __name__ == '__main__':
    logging.debug('starting flask app')
    app.run(debug=config.FLASK_DEBUG, host=config.LISTENING_HOST, threaded=True)
