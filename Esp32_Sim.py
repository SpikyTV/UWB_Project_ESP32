import csv
import os
import logging

# threading and sync
import threading

# MQTT client for ESP32 communication
import paho.mqtt.client as mqtt

# messaging, command & data handling
from queue import Queue
import json

#for creatíng a mac
import uuid

#old imports
import time
import random
import math

class ESP32_Sim:
    def __init__(self):
        
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        console = logging.StreamHandler()
        console.setFormatter(formatter)

        file = logging.FileHandler("simulation.log")
        file.setFormatter(formatter)

        logger.addHandler(console)
        logger.addHandler(file)
        
        # data
        self.msg_queue = Queue()
        
        #uuid
        self.ESP_ID = uuid.uuid4().hex[:4]
        
        self.tag = "N/A"
        
        self.cords = 0, 0
        
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        
        
        
        # MQTT client setup (version2)
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.BROKER_IP, self.BROKER_PORT, keepalive=60)
        self.client.loop_start()
        
        print("MQTT server running...")
        
        
        self.start_samples = 30
        self.samples_per_anchor = 10
        
        self.M2 = []
        self.mean_distances = []
        self.std_deviations = []
        self.sample_counts = []
        self.true_distances = []
        
        threading.Thread(target=self.message_processor, daemon=True).start()
        self.push_satus()
    
#====================================================================================
#            mesurment section (welford running value calculation)
#====================================================================================

    #closest disance generation to a real life UWB
    def generate_distance(self, true_distance, std_deviation=0.3):
        noise = random.gauss(0, std_deviation/2)
            
        if random.random() < 0.01:
            noise += random.uniform(0.5, 3)
        
        return true_distance + noise
        
    #running value calculation
    def update_distance_estimate(self, measured_distance, idx):
        n = self.sample_counts[idx]
        
        #to avoid absolute counter
        threshold = max(0.1, 3 * self.std_deviations[idx])
        accept = True if n < self.start_samples else (abs(measured_distance - self.mean_distances[idx]) <= threshold)

        if not accept:
            return
        
        n +=1
        self.sample_counts[idx] = n
            
        delta = measured_distance - self.mean_distances[idx]
        self.mean_distances[idx] += delta / n
        delta2 = measured_distance - self.mean_distances[idx]
        self.M2[idx] += delta * delta2
            
        if n < 2:
            self.std_deviations[idx] = 0.0
        else:
            self.std_deviations[idx] = math.sqrt(self.M2[idx] / (n - 1))
            
    #loops over every anchor to create set of mesurments 
    def simulate_measurements(self):
        r = len(self.true_distances)
        
        for _ in range(self.samples_per_anchor):
            for idx in range(r):
                true_distance = self.true_distances[idx]
                
                #skips mesuurment with it self
                if true_distance < 1e-6:
                    continue
                    
                distance = self.generate_distance(true_distance, 0.3)
                self.update_distance_estimate(distance, idx)
               
    def initiate_lists(self):
        r = len(self.true_distances)
        self.mean_distances = [0.0] * r
        self.std_deviations = [0.0] * r
        self.M2 = [0.0] * r
        self.sample_counts = [0] * r
    
    def start_measurement(self):
        logging.info("Initializing ranging simulation")
        
        self.initiate_lists()
        
        self.simulate_measurements()
        self.publish_measurement()

        while self.tag == "tag":
            time.sleep(0.5)
            self.simulate_measurements()
            self.push_ranging()
        
#====================================================================================
#            comms section (mqtt)
#====================================================================================    
    
    def push_satus(self):
        self.status_payload = {
            "status": "online",
            "esp_id": self.ESP_ID,
            "tag": self.tag,
            "cords": self.cords,
        }
        
        topic = f"hub/esp/{self.ESP_ID}/status"
        self.client.publish(topic, json.dumps(self.status_payload), retain=True, qos=1)
        
    def push_ranging(self):
        payload = {
            "mean_distances": self.mean_distances,
            "std_deviations": self.std_deviations,
            "cords": self.cords,
        }
        
        topic = f"hub/esp/{self.ESP_ID}/ranging"
        self.client.publish(topic, json.dumps(payload), qos=0)
        
    def rec_config(self, data):
        
        if self.ESP_ID != data.get("esp_id"):
            self.ESP_ID = data.get("esp_id")
            
            #resubscribe under propper id
            self.client.subscribe(f"hub/esp/{self.ESP_ID}/cfg/config")
            self.client.subscribe(f"hub/esp/{self.ESP_ID}/cmd/measure")
            self.client.subscribe(f"hub/esp/{self.ESP_ID}/cmd/move")
        
        self.tag = data.get("tag")
        self.cords = (float(data.get("x")), float(data.get("y")))
        self.samples_per_anchor = data.get("samples_per_anchor")

        self.push_satus()
        
    def rec_others(self, data):
        nodes = data.get("nodes")
        
        self.true_distances.clear()
        
        x0, y0 = self.cords
        for node in nodes:
            x1, y1 = node.get("cords")
            
            d = math.hypot(x1 - x0, y1 - y0)
            self.true_distances.append(d)
       
    def on_connect(self, client, userdata, flags, reason_code, properties):
        # MQTT on_connect callback
        if reason_code == 0:
            logging.info(f"Connected to MQTT broker as ESP32 under {self.ESP_ID}")
            
            self.client.subscribe(f"hub/esp/{self.ESP_ID}/cfg/config")
            self.client.subscribe("hub/esp/bcast/cfg/others")
            self.client.subscribe(f"hub/esp/{self.ESP_ID}/cmd/measure")
            self.client.subscribe(f"hub/esp/{self.ESP_ID}/cmd/move")
        else:
            logging.error(f"Connection failed (reason_code={reason_code})")
        
    def on_message(self, client, userdata, msg):
        # MQTT on_message callback
        # queue to separate network from data processing
        try:
            topic_parts = msg.topic.split("/")
            payload = json.loads(msg.payload.decode("utf-8"))
            self.msg_queue.put((topic_parts[3], topic_parts[4], payload))
        except Exception as e:
            logging.error("Error processing message: %s", e)
            
    def message_processor(self):
        # processes MQTT messages
        while True:
            category, command, data = self.msg_queue.get()  # blocks until message is available

            if category == "cfg":
                if command == "config":
                    self.rec_config(data)
                elif command == "others":
                    self.rec_others(data)
                else:
                    logging.error("Unknown command: %s", command)
            elif category == "cmd":
                if command == "measure":
                    threading.Thread(target=self.start_measurement, daemon=True).start()
                elif command == "move":
                    self.toggle_move()
                else:
                    logging.error("Unknown command: %s", command)
            else:
                logging.error("Unknown category: %s", category)
                
#====================================================================================
#            movement section
#====================================================================================
    def pick_new_target(self):
        self.target = (
            random.uniform(5, 45),
            random.uniform(6, 35)
        )
        self.speed = random.uniform(2, 8)  # m/s
        
    def update(self):
        dt = 1 / 120
        
        x, y = self.cords
        tx, ty = self.target

        dx = tx - x
        dy = ty - y
        distance = math.hypot(dx, dy)

        if distance < 0.1:
            self.pick_new_target()
            return

        dx /= distance
        dy /= distance

        x += dx * self.speed * dt
        y += dy * self.speed * dt

        self.cords = (x, y)
        
    def run_cords(self):
        self.pick_new_target()
        
        while True:
            self.update()
            time.sleep(1/120)
    