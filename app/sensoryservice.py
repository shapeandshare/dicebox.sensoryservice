#!flask/bin/python
###############################################################################
# Sensory Service
#   Handles requests for sensory information, and storage of classified
#    samples.
#
# Copyright (c) 2017-2019 Joshua Burt
###############################################################################


###############################################################################
# Dependencies
###############################################################################
import dicebox.docker_config
import dicebox.sensory_interface
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


# Config
config_file = './dicebox.config'
CONFIG = dicebox.docker_config.DockerConfig(config_file)


###############################################################################
# Allows for easy directory structure creation
# https://stackoverflow.com/questions/273192/how-can-i-create-a-directory-if-it-does-not-exist
###############################################################################
def make_sure_path_exists(path):
    try:
        if os.path.exists(path) is False:
            os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise


###############################################################################
# Setup logging
###############################################################################
make_sure_path_exists(CONFIG.LOGS_DIR)
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S %p',
    level=logging.DEBUG,
    filemode='w',
    filename="%s/sensoryservice.%s.log" % (CONFIG.LOGS_DIR, os.uname()[1])
)


###############################################################################
# Generate our Sensory Service Interface
###############################################################################
ssc = dicebox.sensory_interface.SensoryInterface('server', config_file)


# Write category map to disk for later usage directly with weights.
logging.debug('writing category map to %s/category_map.json' % CONFIG.WEIGHTS_DIR)
make_sure_path_exists(CONFIG.WEIGHTS_DIR)
with open('%s/category_map.json' % CONFIG.WEIGHTS_DIR, 'w') as cat_map_file:
    cat_map_file.write(json.dumps(ssc.fsc.CATEGORY_MAP))


###############################################################################
# Stores incoming sensory data
###############################################################################
def sensory_store(data_dir, data_category, raw_image_data):
    filename = "%s" % datetime.now().strftime('%Y-%m-%d_%H_%M_%S_%f.png')
    path = "%s%s/" % (data_dir, data_category)
    full_filename = "%s%s" % (path, filename)
    logging.debug("(%s)" % (full_filename))
    make_sure_path_exists(path)
    with open(full_filename, 'wb') as f:
        f.write(raw_image_data)
    return True


###############################################################################
# Used for creating small sensory batches
###############################################################################
def sensory_request(batch_size, noise=0):
    data, labels = ssc.get_batch(batch_size, noise)
    return data, labels


###############################################################################
# Used for large batches.  Uses an external message system to issue batch
# request to a separate service.  Uses 'sharding' to allow for parallel
# processing by multiple batch processors.
###############################################################################
def sensory_batch_request(batch_size, noise=0):
    sensory_batch_request_id = uuid.uuid4()

    # determine how many shards need to be created for the batch
    shards = 1
    tail_shard_size = 0
    if batch_size > CONFIG.SENSORY_SERVICE_SHARD_SIZE:
        tail_shard_size = batch_size % CONFIG.SENSORY_SERVICE_SHARD_SIZE
        shards = (batch_size - (batch_size % CONFIG.SENSORY_SERVICE_SHARD_SIZE))/CONFIG.SENSORY_SERVICE_SHARD_SIZE

    try:
        ## Submit our message
        url = CONFIG.SENSORY_SERVICE_RABBITMQ_URL
        # logging.debug(url)
        parameters = pika.URLParameters(url)
        connection = pika.BlockingConnection(parameters=parameters)

        channel = connection.channel()

        channel.queue_declare(queue=CONFIG.SENSORY_SERVICE_RABBITMQ_BATCH_REQUEST_TASK_QUEUE, durable=True)

        sensory_request = {}
        sensory_request['sensory_batch_request_id'] = str(sensory_batch_request_id)
        if batch_size > CONFIG.SENSORY_SERVICE_SHARD_SIZE:
            sensory_request['batch_size'] = CONFIG.SENSORY_SERVICE_SHARD_SIZE
        else:
            sensory_request['batch_size'] = batch_size
        sensory_request['noise'] = noise

        for shard in range(0, shards):
            # send message
            channel.basic_publish(exchange=CONFIG.SENSORY_SERVICE_RABBITMQ_EXCHANGE,
                                  routing_key=CONFIG.SENSORY_SERVICE_RABBITMQ_BATCH_REQUEST_ROUTING_KEY,
                                  body=json.dumps(sensory_request),
                                  properties=pika.BasicProperties(
                                      delivery_mode=2,  # make message persistent
                                  ))
            logging.debug(" [x] Sent %r", json.dumps(sensory_request))
        if tail_shard_size > 0:
            # send final message of size tail_shard_size
            sensory_request['batch_size'] = tail_shard_size
            channel.basic_publish(exchange=CONFIG.SENSORY_SERVICE_RABBITMQ_EXCHANGE,
                                  routing_key=CONFIG.SENSORY_SERVICE_RABBITMQ_BATCH_REQUEST_ROUTING_KEY,
                                  body=json.dumps(sensory_request),
                                  properties=pika.BasicProperties(
                                      delivery_mode=2,  # make message persistent
                                  ))
            logging.debug(" [x] Sent %r", json.dumps(sensory_request))
        connection.close()
    except:
        # something went wrong..
        logging.error('we had a failure sending the batch requests to the message system')
        return None
    return sensory_batch_request_id


###############################################################################
# returns a queued batch order message for the supplied request id if possible
###############################################################################
def sensory_batch_poll(batch_id):
    # lets try to grab more than one at a time // combine and return
    # since this is going to clients lets reduce chatter

    data = None
    label = None

    url = CONFIG.SENSORY_SERVICE_RABBITMQ_URL
    # logging.debug(url)
    parameters = pika.URLParameters(url)

    try:
        connection = pika.BlockingConnection(parameters=parameters)
        channel = connection.channel()

        method_frame, header_frame, body = channel.basic_get(batch_id)
        if method_frame:
            logging.debug("%s %s %s", method_frame, header_frame, body)
            message = json.loads(body)
            label = message['label']
            data = message['data']
            logging.debug(label)
            logging.debug(data)
            channel.basic_ack(method_frame.delivery_tag)
        else:
            logging.debug('no message returned')
    except:
        logging.debug('requested queue not found.')
    finally:
        connection.close()

    return data, label


###############################################################################
# Create the flask, and cors config
###############################################################################
app = Flask(__name__)
cors = CORS(app, resources={r"/api/*": {"origins": "http://localhost:*"}})


###############################################################################
# Provides categories for client consumption
###############################################################################
@app.route('/api/sensory/category', methods=['GET'])
def make_api_category_map_public():
    if request.headers['API-ACCESS-KEY'] != CONFIG.API_ACCESS_KEY:
        abort(403)
    if request.headers['API-VERSION'] != CONFIG.API_VERSION:
        abort(400)

    return make_response(jsonify({'category_map': ssc.fsc.CATEGORY_MAP}), 200)


###############################################################################
# Used to store sensory data
###############################################################################
@app.route('/api/sensory/store', methods=['POST'])
def make_api_sensory_store_public():
    if request.headers['API-ACCESS-KEY'] != CONFIG.API_ACCESS_KEY:
        abort(403)
    if request.headers['API-VERSION'] != CONFIG.API_VERSION:
        abort(400)
    if not request.json:
        abort(500)

    if 'name' not in request.json:
        abort(500)
    if 'width' not in request.json:
        abort(500)
    if 'height' not in request.json:
        abort(500)
    if 'height' not in request.json:
        abort(500)
    if 'data' not in request.json:
        abort(500)
    if 'data' in request.json and type(request.json['data']) != unicode:
        abort(500)

    dataset_name = request.json.get('name')
    image_width = request.json.get('width')
    image_height = request.json.get('height')
    category = request.json.get('category')
    encoded_image_data = request.json.get('data')
    decoded_image_data = base64.b64decode(encoded_image_data)

    network_name = "%s_%ix%i" % (dataset_name, image_width, image_height)
    data_directory = "%s/%s/data/" % (CONFIG.DATA_BASE_DIRECTORY, network_name)

    return_code = sensory_store(data_directory, category, decoded_image_data)
    return make_response(jsonify({'sensory_store': return_code}), 200)


###############################################################################
# For Requesting big batches
###############################################################################
@app.route('/api/sensory/batch', methods=['POST'])
def make_api_sensory_batch_request_public():
    if request.headers['API-ACCESS-KEY'] != CONFIG.API_ACCESS_KEY:
        logging.debug('bad access key')
        abort(403)
    if request.headers['API-VERSION'] != CONFIG.API_VERSION:
        logging.debug('bad access version')
        abort(400)
    if not request.json:
        logging.debug('request not json')
        abort(500)

    if 'batch_size' not in request.json:
        logging.debug('batch size not in request')
        abort(500)
    if 'noise' not in request.json:
        logging.debug('noise not in request')
        abort(500)

    batch_size = request.json.get('batch_size')
    noise = request.json.get('noise')

    sensory_batch_request_id = sensory_batch_request(batch_size, noise)
    return make_response(jsonify({'batch_id': sensory_batch_request_id}), 202)


###############################################################################
# async request queue polling end point
###############################################################################
@app.route('/api/sensory/poll', methods=['POST'])
def make_api_sensory_poll_public():
    if request.headers['API-ACCESS-KEY'] != CONFIG.API_ACCESS_KEY:
        logging.debug('bad access key')
        abort(403)
    if request.headers['API-VERSION'] != CONFIG.API_VERSION:
        logging.debug('bad access version')
        abort(400)
    if not request.json:
        logging.debug('request not json')
        abort(500)
    if 'batch_id' not in request.json:
        logging.debug('batch id not in request')
        abort(500)

    batch_id = request.json.get('batch_id')

    data, label = sensory_batch_poll(batch_id)
    return make_response(jsonify({
        'label': numpy.array(label).tolist(),
        'data': numpy.array(data).tolist()
    }), 200)


###############################################################################
# for small batches..
###############################################################################
@app.route('/api/sensory/request', methods=['POST'])
def make_api_sensory_request_public():
    if request.headers['API-ACCESS-KEY'] != CONFIG.API_ACCESS_KEY:
        logging.debug('bad access key')
        abort(403)
    if request.headers['API-VERSION'] != CONFIG.API_VERSION:
        logging.debug('bad access version')
        abort(400)
    if not request.json:
        logging.debug('request not json')
        abort(500)

    if 'batch_size' not in request.json:
        logging.debug('batch size not in request')
        abort(500)
    if 'noise' not in request.json:
        logging.debug('noise not in request')
        abort(500)

    batch_size = request.json.get('batch_size')
    noise = request.json.get('noise')

    data, labels = sensory_request(batch_size, noise)
    return make_response(jsonify({
        'labels': numpy.array(labels).tolist(),
        'data': numpy.array(data).tolist()
    }), 201)


###############################################################################
# Returns API version
###############################################################################
@app.route('/api/version', methods=['GET'])
def make_api_version_public():
    return make_response(jsonify({'version':  str(CONFIG.API_VERSION)}), 200)


###############################################################################
# Super generic health end-point
###############################################################################
@app.route('/health/plain', methods=['GET'])
@cross_origin()
def make_health_plain_public():
    return make_response('true', 200)


###############################################################################
# 404 Handler
###############################################################################
@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)


###############################################################################
# main entry point, thread safe
###############################################################################
if __name__ == '__main__':
    logging.debug('starting flask app')
    app.run(debug=CONFIG.FLASK_DEBUG, host=CONFIG.LISTENING_HOST, threaded=True)
