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
import running_value_calculation

class ESP32_Sim:
    def __init__(self):
        # data
        self.msg_queue = Queue()
        
        #uuid
        self.ESP_ID = uuid.uuid4().hex[:4]
        
        self.tag = ""
        
        self.cords = 0, 0
        
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        
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
        self.start_samples = 200
        self.max_error = 0.5
        self.number_of_samples = 200
        
        self.list_distance = []
        self.list_dispersion = []
        
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
        self.cords = (float(data.get("x")), float(data.get("y")))
        
        x, y = self.cords
        
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

    #running value
    def add(self, value: float):
        # Always take first start_samples measurements
        if self.count < self.start_samples:
            accept = True
        else:
            # Accept only if within max_error from current mean
            accept = abs(value - self.mean) <= self.max_error

        if accept:
            self.count += 1
            delta = value - self.mean
            self.mean += delta / self.count
            delta2 = value - self.mean
            self.M2 += delta * delta2
        else:
            pass

    def get_mean(self) -> float:
        return self.mean

    def get_dispersion(self) -> float:
        if self.count < 2:
            return 0.0
        variance = self.M2 / (self.count - 1)
        return variance ** 0.5

    def make_mesurements(self, number_of_mesurments, real_distance):

        self.count = 0
        self.mean = 0.0
        self.M2 = 0.0

        for _ in range(number_of_mesurments):
            distance = running_value_calculation.generate_distance(real_distance)
            self.add(distance)

        self.list_distance.append(round(abs(self.get_mean()), 2))
        self.list_dispersion.append(round(abs(self.get_dispersion()), 2))
        
        print(self.list_distance)
        print(self.list_dispersion)
        
    
    def start_measurement(self):
        print("Starting measurement routine...")
       
        self.list_distance = []
        self.list_dispersion = []

        
        for other_id, data in self.others.items():
            
            x2, y2 = data.get("cords")
            tag = data.get("tag")
            
            if tag == "anch":
                # Skip measuring distance to itself
                if other_id == self.ESP_ID:
                    self.list_distance.append(0.0)
                    self.list_dispersion.append(0.0)
                    continue
                    
                #dont ask me I dont remember (real distance)
                x1, y1 = self.cords
                distance = math.hypot(x2 - x1, y2 - y1)

                if self.tag == "anch":
                    self.make_mesurements(1500, distance)
                elif self.tag == "tag":
                    #only 20 samples per anchor when you are tag (expecte to take around 0.05 sec)
                    self.make_mesurements(20, distance)
       
       
       
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
            
            time.sleep(int(self.ESP_ID.split("_")[-1]) * 0.05)
            
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