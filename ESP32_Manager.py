import os
import logging

# threading and sync
import threading

# MQTT client for ESP32 communication
import paho.mqtt.client as mqtt

# messaging, command & data handling
from queue import Queue
import json

# data structures
from dataclasses import dataclass, field, asdict
from typing import Tuple, List

from Esp32_Sim import ESP32_Sim


@dataclass
class Nodes:
    # single UWB node (bouth anchor and tag), stores all needed atributes
    
    id: str
    tag: str
    cords: tuple[float, float]
    
    def __str__(self):
        # user readable node print out
        
        return (f"{self.id} | {self.tag} | "
                f"{self.cords[0]:.2f}/{self.cords[1]:.2f}")

#the naming could use some work
class ESP32_Manager:
    def __init__(self):
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        console = logging.StreamHandler()
        console.setFormatter(formatter)

        file = logging.FileHandler(f"ESP_manager.log")
        file.setFormatter(formatter)

        logger.addHandler(console)
        logger.addHandler(file)
        
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        
        # data
        self.msg_queue = Queue()
        
        
        # MQTT client setup (version2)
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.BROKER_IP, self.BROKER_PORT, keepalive=60)
        self.client.loop_start()
        
        print("MQTT server running...")
        
        
        
        self.nodes = {}
        
#====================================================================================
#            comms basic section (mqtt)
#====================================================================================       
        
    def on_connect(self, client, userdata, flags, reason_code, properties):
        # MQTT on_connect callback
        if reason_code == 0:
            logging.info("Connected to MQTT broker")
            self.client.subscribe("hub/esp/+/status")
            self.client.subscribe("hub/manager/cmd/create_sim")
            self.client.subscribe("hub/manager/cmd/config_push")
        else:
            logging.error(f"Connection failed (reason_code={reason_code})")
        
    def on_message(self, client, userdata, msg):
        # MQTT on_message callback
        try:
            topic_parts = msg.topic.split("/")
            raw = msg.payload.decode("utf-8").strip()
            if raw:
                payload = json.loads(raw)
            else:
                payload = {}
            self.msg_queue.put((topic_parts, payload))
        except Exception as e:
            logging.error("Error processing message: %s", e)    
        
    def message_processor(self):
        # processes MQTT messages
        while True:
            topic_parts, data = self.msg_queue.get()  # blocks until message is available

            if topic_parts[2] == "cmd":
                if topic_parts[3] == "create_sim":
                    amount = int(data.get("amount", 1))
                    for _ in range(amount):
                        self.add_ESP32()
                elif topic_parts[3] == "config_push":
                    self.update_client(data)
                else:
                    logging.error(f"unknown cmd: {topic_parts}") 
            elif topic_parts[1] == "esp":
                self.update_node(data)
            else:
                logging.error(f"unknown topic: {topic_parts}")  
            
#====================================================================================
#            comms section (mqtt)
#====================================================================================           
        
    def update_node(self, data):
        node_id = data.get("esp_id")
        tag = data.get("tag")
        cords = data.get("cords")
        
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.tag = tag
            node.cords = cords
        else: 
            self.nodes[node_id] = Nodes(node_id, tag, cords)
            
        self.send_UIData()
             
    def update_client(self, data):
        payload = {
            "tag": data.get("tag"),
            "cords": data.get("cords"),
            "samples_per_anchor": data.get("samples_per_anchor")
        }
        
        topic = f"hub/esp/{data.get('esp_id')}/cfg/config"
        
        self.client.publish(topic, json.dumps(payload), retain=True, qos=1)
             
    def send_UIData(self):
        payload = {"nodes": [asdict(node) for node in self.nodes.values()]}
        
        topic = "hub/manager/state/nodes"
        self.client.publish(topic, json.dumps(payload), retain=True, qos=1)
    
    def add_ESP32(self):
        logging.info("adding ESP32")
        esp32 = ESP32_Sim()
        threading.Thread(target=esp32.message_processor, daemon=True).start()
        

if __name__ == "__main__":
    manager = ESP32_Manager()
    manager.message_processor()