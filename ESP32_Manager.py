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
    real: tuple[float, float]
    
    def __str__(self):
        # user readable node print out
        
        return (f"{self.id} | {self.tag} | "
                f"{self.real[0]:.2f}/{self.real[1]:.2f}")

#the naming could use some work
class ESP32_Manager:
    def __init__(self):
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        
        # MQTT Topics
        self.TOPIC = "hub/+/data"     
        self.TOPIC2 = "hub/+/command"     
        self.TOPIC3 = "hub/ESP32_Manager/register"     
        self.TOPIC6 = "hub/ESP32_Manager/update" 
        self.TOPIC4 = "hub/+/UIData"
        self.TOPIC5 = "hub/ESP32_Manager/UICommand"
        
        # MQTT client setup (version2)
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.BROKER_IP, self.BROKER_PORT, keepalive=60)
        self.client.loop_start()
        
        print("MQTT server running...")
        
        # data
        self.msg_queue = Queue()
        
        self.nodes = {}
        
        
    def register_client(self, node_id):
        
        id = f"ESP32_{len(self.nodes)}"
        self.nodes[id] = Nodes(id, "NotSet", (0, 0))
        
        payload = {
            "type": "config",
            "id": id,
            "tag": "NotSet",
            "x": 0,
            "y": 0,
        }
        
        topic = f"hub/{node_id}/command"
        
        print(f"sending data to {topic}")
        
        self.client.publish(topic, json.dumps(payload), qos=1)
        
    def update_client(self, data):
        node = self.nodes[data.get("id")]
        
        node.tag = data.get("tag")
        node.real = (data.get("x"), data.get("y"))
        
        self.send_UIData()
        
    def send_UIData(self):
        payload = {"nodes": [asdict(node) for node in self.nodes.values()]}
        
        topic = f"hub/ESP32_Manager/UIData"
        self.client.publish(topic, json.dumps(payload), qos=1)
    
    def on_connect(self, client, userdata, flags, reason_code, properties):
        # MQTT on_connect callback
        if reason_code == 0:
            print("Connected to MQTT broker")
            self.client.subscribe(self.TOPIC3) # comunication with ESP32
            self.client.subscribe(self.TOPIC5) # comunication with gui
            self.client.subscribe(self.TOPIC6) # comunication with ESP32
        else:
            print(f"Connection failed (reason_code={reason_code})")
        
    def on_message(self, client, userdata, msg):
        # MQTT on_message callback
        # queue to separate network from data processing
        try:
            topic_parts = msg.topic.split("/")
            payload = json.loads(msg.payload.decode("utf-8"))
            self.msg_queue.put((topic_parts[2], payload))
        except Exception as e:
            print("Error processing message:", e)

    def message_processor(self):
        # processes MQTT messages
        while True:
            in_topic, data = self.msg_queue.get()  # blocks until message is available

            print(f"Processing {in_topic}")
            
            if in_topic == "register":
                self.register_client(data.get("id"))
            elif in_topic == "update":
                self.update_client(data)
            elif in_topic == "UICommand":
                self.handle_UIcommand(data)
            else:
                print(f"unknown topic: {in_topic}")
    
    def add_ESP32(self):
        print ("adding ESP32")
        esp32 = ESP32_Sim()
        threading.Thread(target=esp32.message_processor, daemon=True).start()
        
    def configure_ESP32(self, tag, cords):
        print (f"configuring ESP32 WITH {tag} and {cords}")

    def send_UIData(self):
        payload = {"nodes": [asdict(node) for node in self.nodes.values()]}
        
        topic = f"hub/ESP32_Manager/UIData"
        self.client.publish(topic, json.dumps(payload), qos=1)

    def handle_UIcommand(self, data):
        # command handeling
        command = data.get("command")
        
        print(f"executing command {command}")
        
        if command == "add_ESP32":
            self.add_ESP32()
        elif command == "configure_ESP32":
            tag = data.get("tag")
            cords= data.get("cords")
            self.configure_ESP32(tag, cords)
        elif command == "send_nodes":
            self.send_UIData()

if __name__ == "__main__":
    manager = ESP32_Manager()
    manager.message_processor()