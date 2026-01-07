import _thread
import threading
import time
import random
import Esp32

#the naming could use some work
class mainThing:
    def __init__(self):
           #config section (move to config file you lazy)
           self.brokerIP = "127.0.0.1" #mosquitto
            
           self.ID = 0
           self.number_of_anchors = 5
           self.esp_objects = []

           print("boot")

           self.running()

    def running(self):
        print("running")

        self.esp_objects = []

        for i in range(self.number_of_anchors):
            x = random.uniform(1, 20)
            y = random.uniform(1, 20)
            esp = Esp32.ESP32(x, y, self.brokerIP, self.ID, "anch")
            self.ID += 1 
            self.esp_objects.append(esp)
            time.sleep(0.5)

        x = random.uniform(1, 20)
        y = random.uniform(1, 20)
        tag_esp = Esp32.ESP32(x, y, self.brokerIP, self.ID, "tag")
        self.ID += 1 
        tag_esp.set_esp_objects(self.esp_objects)
        
        for esp in self.esp_objects:
            esp.set_esp_objects(self.esp_objects)
        
        print("ESP32 creation complete")

        while True:
            pass

if __name__ == "__main__":
    mainThing()