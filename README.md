Sensory Service
===============
Provides an end-point that performs input data storage and retrieval via REST API calls.
* Stores data with classifications that are sent to it from the client/supervisored trainer.
* Provides data sets for the stand-alone trainer while building the weights.
    * For small batches of the data a single API call can be used.  
    * For large batches a batch order is created and the trainer polls the sensory service to get all the training data. (The sensory service pulls the data off a RabbitMQ queue with a matching batch order id.)


### Getting Started
The application is meant to be run within a docker container.  If you need to run it outside of the container for development you will need to make the core libraries and dicebox.config file available to the application.

**Development Runtime Layout**
```
/root
    /app
        /lib 
        /dicebox.config
        [...]
    /assets
    /dicebox
    [...]
```
* Symbolicly link /root/dicebox -> /root/app/lib
* Copy dicebox.config into /root/app

**Start the service (development only):**
```
    python ./sensory_service.py
```

I've tested running the sensory service with uwsgi, and proxied through nginx.  Nginx configurations can be found within ./nginx of this repository.
```
uwsgi --http-socket 127.0.0.1:5000 --manage-script-name --mount /=sensory_service.py --plugin python,http --enable-threads --callable app —master
```

### RabbitMQ Configuration
* Service account for the service to connect to the vhost
* vhost: sensory
* exchange: sensory.exchange
  * type: topic
* queue: sensory.batch.request.task.queue
* binding:
  * (exchange) sensory.exchange >--> (routing key): task_queue >--> (queue) sensory.batch.request.task.queue


### Production Deployment

**Docker Container**

The recommended way to run the service is by using the official provided docker container. The container is published to Docker Hub [here](https://hub.docker.com/r/shapeandshare/dicebox.sensoryservice/).

The container should be deployed to a Docker Swarm as a service, or as a stand-alone container within a Docker Engine.

**Example**
```
docker service create \
--detach=false \
--publish 8002:80 \
--replicas 1 \
--log-driver json-file \
--mount type=volume,volume-driver=cloudstor:aws,source=dicebox,destination=/dicebox \
--name sensoryservice shapeandshare/dicebox.sensoryservice
```

How to apply rolling updates of the service within the swarm:
```
docker service update --image shapeandshare/dicebox.sensoryservice:latest sensoryservice
```

In the examples above the Docker Swarm was deployed to AWS and had the Cloudstor:aws plugin enabled and active.
The sensory service containers will store and read data from the shared storage.

**Global shared Cloudstor volumes mounted by all tasks in a swarm service.**

The below command is an example of how to create the shared volume within the docker swarm:
```
docker volume create -d "cloudstor:aws" --opt backing=shared dicebox
```


Contributing
------------
1. Fork the [repository](https://github.com/shapeandshare/dicebox.sensoryservice) on Github
2. Create a named feature branch (like `add_component_x`)
3. Write your change
4. Write tests for your change (if applicable)
5. Run the tests, ensuring they all pass
6. Submit a Pull Request using Github

License and Authors
-------------------
MIT License

Copyright (c) 2017-2019 Joshua C. Burt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.