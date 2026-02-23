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
        
        self.tag = ""
        
        self.cords = 0, 0
        
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        
        self.sample_id = 0
        self.mesurment_id = 0
        self.mesuring_anch = 0
        
        # MQTT Topics
        self.TOPIC = "hub/+/data"     
        self.TOPIC2 = "hub/+/command"     
        self.TOPIC3 = "hub/+/register"     
        self.TOPIC4 = "hub/+/UIData"
        self.TOPIC5 = "hub/+/UICommand"
        self.TOPIC6 = "hub/+/uwb"
        
        # MQTT client setup (version2)
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.BROKER_IP, self.BROKER_PORT, keepalive=60)
        self.client.loop_start()
        
        print("MQTT server running...")
        
        self.count = 0
        self.mean = 0.0
        self.M2 = 0.0
        self.start_samples = 10
        self.max_error = 0.5
        self.number_of_samples = 200
        
        self.list_distance = []
        self.list_dispersion = []
        self.list_distance = []
        
        self.others = {}
        
        first_reg_payload = {
            "id": self.ESP_ID,
        }
        
        topic = "hub/ESP32_Manager/register"

        #on connect sends register topic with 1 send garanteed
        self.client.publish(topic, json.dumps(first_reg_payload), qos=1)
    
    def config(self, data):
        self.ESP_ID = data.get("id")
        self.tag = data.get("tag")
        x = float(data.get("x"))
        y = float(data.get("y"))
        self.cords = (x, y)
        
        payload = {
            "id": self.ESP_ID,
            "x": x,
            "y": y,
            "tag": self.tag
        }
        
        topic = f"hub/ESP32_Manager/update"

        #on connect sends register topic with 1 send garanteed
        self.client.publish(topic, json.dumps(payload), qos=1)
        
    def register(self):
        x, y = self.cords
        
        registration_payload = {
            "esp_id": self.ESP_ID,
            "x": float(x),
            "y": float(y),
            "tag": self.tag
        }
        
        topic = f"hub/solver/register"

        #on connect sends register topic with 1 send garanteed
        self.client.publish(topic, json.dumps(registration_payload), qos=1)
        
    
    def on_connect(self, client, userdata, flags, reason_code, properties):
        # MQTT on_connect callback
        if reason_code == 0:
            print(f"Connected to MQTT broker as ESP32 under {self.ESP_ID}")
            self.client.subscribe(self.TOPIC2) # comunication with ESP32
            self.client.subscribe(self.TOPIC6)
        else:
            print(f"Connection failed (reason_code={reason_code})")
        
    def on_message(self, client, userdata, msg):
        # MQTT on_message callback
        # queue to separate network from data processing
        try:
            topic_parts = msg.topic.split("/")
            payload = json.loads(msg.payload.decode("utf-8"))
            self.msg_queue.put((topic_parts[1], payload))
        except Exception as e:
            print("Error processing message:", e)

    #message to send mesurements to server
    def send_measurement(self):
        x, y = self.cords
        
        payload = {
            "tag": self.tag,
            "esp_id": self.ESP_ID,
            "distance": self.list_distance,
            "dispersion": self.list_dispersion,
            "x": x,
            "y": y
        }
        
        topic = f"hub/{self.ESP_ID}/data"
        
        print("sending data")
        self.client.publish(topic, json.dumps(payload), qos=0)
        
    def append_csv_row(self, csv_path: str, row: dict):
        file_exists = os.path.exists(csv_path)
        fieldnames = list(row.keys())

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)    
    
   
       
       
        self.send_measurement()
       
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
    
    def handle_command(self, data):
        command = data.get("command")
        
        
        if command == "start_measurement":
            threading.Thread(target=self.start_measurement, daemon=True).start()
        elif command == "start_tag":
            threading.Thread(target=self.run_cords, daemon=True).start()
            while True:
                self.start_measurement()
                time.sleep(0.05)
        elif command == "uwb":
            
            time.sleep(1 + (int(self.ESP_ID.split("_")[-1]) * 0.05))
            
            payload = {
                "type": "uwb",
                "id": self.ESP_ID,
                "cords": self.cords,
                "tag": self.tag
            }
            
            topic = "hub/uwb/uwb"

            self.client.publish(topic, json.dumps(payload), qos=1)
            
        
    def message_processor(self):
        # processes MQTT messages
        while True:
            uuid, data = self.msg_queue.get()  # blocks until message is available

            type = data.get("type")
            
            if uuid in (self.ESP_ID, "uwb"):
                if type == "config":
                    self.config(data)
                elif type == "final_config":
                    self.config(data)
                    self.register()
                elif type == "command":
                    threading.Thread(target=self.handle_command, args=(data,), daemon=True).start()
                elif type == "uwb":
                    self.others[data.get("id")] = {"cords": data.get("cords"), "tag": data.get("tag")}
                else:
                    print(f"unknown type: {type}")
                    
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
    def simulate_measurements(self, samples_per_anchor):
        r = len(self.true_distances)
        
        for _ in range(samples_per_anchor):
            for idx in range(r):
                true_distance = self.true_distances[idx]
                
                #skips mesuurment with it self
                if true_distance == 0:
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
        self.simulate_measurements(self.samples_per_anchor)
        
        self.publish_measurement()