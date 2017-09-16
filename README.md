# dicebox
               Let's shake things up!

Overview
--------
An image classification and training system built with SOA (Service-Oriented Architecture) in mind.  The project includes several client implementations, and future enhancements will continue to expand the API capabilities.

1. **Visual Image Classification**

    Dicebox is a visual classification system.  It can be reconfigured for different image sizes and categories.

2. **Evolutionary Neural Network**

    Dicebox is capable of being applied to a large variety of classification problems.  Sometimes unique or novel problems need to be solved and a neural network structure is unknown.  In this case dicebox provides a means to evolve a network tailored to the particular problem.

3. **Service-Oriented Architecture**
   
*   The trained neural network is accessed through a REST API.  
*   The Web Client (and supervised trainer) stores data to an AWS EFS via the REST API.
*   The Trainer uses the REST API for training data



High Level Components
---------------------

![Dicebox Services Diagram](https://github.com/shapeandshare/dicebox/raw/master/assets/Dicebox%20Services%20Diagram.090217.png)

* **Sensory Service**

    The sensory service is a REST API that will store data that needs to be added to training set for a given classification.  It is primary consumed by the stand-alone trainer.

    Provides input data directly for small batch sizes, or can queue up large batch orders for creation by the batch processor.
 


Sensory Service
===============
Provides an end-point that performs input data storage and retrieval via REST API calls.
* Stores data with classifications that are sent to it from the client/supervisored trainer.
* Provides data sets for the stand-alone trainer while building the weights.
    * For small batches of the data a single API call can be used.  
    * For large batches a batch order is created and the trainer polls the sensory service to get all the training data. (The sensory service pulls the data off a RabbitMQ queue with a matching batch order id.)


**Start the service (development only):**
```
    python ./sensory_service.py
```

I've tested running the sensory service with uwsgi, and proxied through nginx.  Nginx configurations can be found within ./nginx of this repository.
```
uwsgi --http-socket 127.0.0.1:5000 --manage-script-name --mount /=sensory_service.py --plugin python,http --enable-threads --callable app —master
```

### Production Deployment

**Docker Container**

The recommended way to run the service is by using the official provided docker container.
The container should be deployed to a Docker Swarm as a service.

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
1. Fork the repository on Github
2. Create a named feature branch (like `add_component_x`)
3. Write your change
4. Write tests for your change (if applicable)
5. Run the tests, ensuring they all pass
6. Submit a Pull Request using Github

License and Authors
-------------------
MIT License

Copyright (c) 2017 Joshua C. Burt

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