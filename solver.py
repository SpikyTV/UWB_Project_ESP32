import csv
import os

# threading and sync
import threading

from filterpy.kalman import KalmanFilter

# NumPy for vector and matrix
import numpy as np


# SciPy solvers:
# - least_squares: position estimationd
# - orthogonal_procrustes: rotation translation correction (RTC)
from scipy.optimize import least_squares
from scipy.linalg import orthogonal_procrustes

# messaging, command & data handling
from queue import Queue
import json

# MQTT client for ESP32 communication
import paho.mqtt.client as mqtt

# data structures
from dataclasses import dataclass, field, asdict
from typing import Tuple, List

import time
import math

@dataclass
class Nodes:
    # single UWB node (bouth anchor and tag), stores all needed atributes
    
    id: str
    tag: str
    real: tuple[float, float]
    calculated: tuple[float, float] = (0.0, 0.0)
    distance: List[float] = field(default_factory=list)
    dispersion: List[float] = field(default_factory=list)
    
    def __str__(self):
        # user readable node print out
        
        return (f"{self.id} | {self.tag} | "
                f"{self.real[0]:.2f}/{self.real[1]:.2f} | "
                f"{self.calculated[0]:.2f}/{self.calculated[1]:.2f}")

class Solver:
    # handles:
    #   communication with ESP32 (UWB)
    #   node registrationa and node data
    #   anchor and tag position estimation
    
    def __init__(self):
        
        self.counter = 0
        self.diff = 0
        self.diff_k = 0
        
        # TODO: move to config / autodiscover
        # MQTT conf
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        
        # MQTT Topics
        self.TOPIC = "hub/+/data"     
        self.TOPIC2 = "hub/+/command"     
        self.TOPIC3 = "hub/solver/register"     
        self.TOPIC4 = "hub/+/UIData"
        self.TOPIC5 = "hub/solver/UICommand"
        
        #threadsafe?
        self.measurement_done = threading.Event()
        
        # queues for threadsafe and nonblocking commands
        self.msg_queue = Queue()
        self.command_queue = Queue()
        
        # dictionary of all nodes
        self.nodes = {}
        
        self.kf = None
        self.kf_last_t = None
        
        # MQTT client setup (version2)
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.BROKER_IP, self.BROKER_PORT, keepalive=60)
        self.client.loop_start()

        print("MQTT server running...")
    
    def get_nodes(self):
        # returns node dictionary
        return self.nodes.values()

    def on_connect(self, client, userdata, flags, reason_code, properties):
        # MQTT on_connect callback
        if reason_code == 0:
            print("Connected to MQTT broker")
            self.client.subscribe(self.TOPIC)
            self.client.subscribe(self.TOPIC3)
            self.client.subscribe(self.TOPIC5)
        else:
            print(f"Connection failed (reason_code={reason_code})")
        
    def on_message(self, client, userdata, msg):
        # MQTT on_message callback
        # queue to separate network from data processing
        try:
            topic_parts = msg.topic.split("/")
            payload = json.loads(msg.payload.decode("utf-8"))
            self.msg_queue.put((topic_parts[1], topic_parts[2], payload))
        except Exception as e:
            print("Error processing message:", e)
            
    def message_processor(self):
        # processes MQTT messages
        while True:
            node_id, in_topic, data = self.msg_queue.get()  # blocks until message is available

            print(f"Processing {in_topic} from {node_id}")
            
            if in_topic == "register":
                threading.Thread(target=self.register_client, args=(data,), daemon=True).start()
            elif in_topic == "data":
                threading.Thread(target=self.receive_data, args=(data,), daemon=True).start()
            elif in_topic == "UICommand":
                threading.Thread(target=self.handle_UIcommand, args=(data,), daemon=True).start()
            else:
                print(f"unknown topic: {in_topic}")

    def register_client(self, data):
        # registers new ESP32 (UWB) node to the solver
        node_id = data.get('esp_id')
        tag = data.get('tag')
        x = data.get('x')
        y = data.get('y')
        
        self.nodes[node_id] = Nodes(node_id, tag, (x, y))
        
        # send updated positions to UI       
        self.send_UIData()
        
        #move to log
        print(f"[SERVER] Registered client: {self.nodes[node_id]}")
    
    def receive_data(self, data):
        # recieves data from nodes
        node_id = data.get('esp_id')
        node = self.nodes.get(node_id)
        
        x = data.get('x')
        y = data.get('y')
        
        
        node.real = (x, y)
        node.distance = data.get('distance')

        node.dispersion = data.get('dispersion')
        
        print(f"incoming data dist: {data.get('distance')}, disp {data.get('dispersion')}")
        
        if data.get('tag') == "tag":
            
            node = self.nodes.get("Kalman")
            node.real = (x, y)
            node.distance = data.get('distance')
            node.dispersion = data.get('dispersion')
                
            self.estimate_tag_position()
        
        #signal Data Recieved
        print(f"[SERVER] Data received from {node_id}")
        self.measurement_done.set()
        
    def measure_anchor(self):
        # starts mesurments between anchors
        # triggers position estimation
        print("[SERVER] Starting measurements...")
        
        payload = {
            "type": "command",
            "command": "uwb"
        }
        
        topic = "hub/uwb/command"

        #on connect sends register topic with 1 send garanteed
        self.client.publish(topic, json.dumps(payload), qos=1)

        anchor_nodes = [node for node in self.nodes.values() if node.tag == "anch"]
        
        time.sleep(2)
        
        for node in anchor_nodes:
            print(f"\n[SERVER] Sending measurement command to client: {node.id}...")
            
            payload = {"type": "command", "command": "start_measurement"}
            topic = f"hub/{node.id}/command"
            
            self.measurement_done.clear()
            self.client.publish(topic, json.dumps(payload), qos=1)
            
            # Wait until ESP returns data or 1:30 min passes
            finished = self.measurement_done.wait(timeout=90)
            
            if not finished:
                print(f"[SERVER] Failed to receive data from node: {node.id}")  
                
            
        self.estimate_anchor_positions_scipy()
                
    def measure_tag(self):
        # starts mesurments between tag and anchors
        # triggers position estimation for tag
        print("[SERVER] Starting measurements...")

        tag_nodes = [node for node in self.nodes.values() if node.tag == "tag"]
        
        for node in tag_nodes:
            
            self.nodes["Kalman"] = Nodes("Kalman", "tag", node.real)
            
            print(f"\n[SERVER] Sending measurement command to client: {node.id}...")
            
            payload = {"type": "command", "command": "start_tag"}
            topic = f"hub/{node.id}/command"
            
            self.measurement_done.clear()
            self.client.publish(topic, json.dumps(payload), qos=1)
            
            # Wait until ESP returns data or 1:30 min passes
            finished = self.measurement_done.wait(timeout=90)
            
            if not finished:
                print(f"[SERVER] Failed to receive data from node: {node.id}")
                
        self.estimate_tag_position()
  
    def build_matrices(self):
        # build matrix for anchors to be used in position estimation
        anchor_nodes = [node for node in self.nodes.values() if node.tag == "anch"]
        
        print(anchor_nodes)

        distance_matrix = [node.distance for node in anchor_nodes]
        dispersion_matrix = [node.dispersion for node in anchor_nodes]

        return np.array(distance_matrix), np.array(dispersion_matrix)
  
    def Correction_pos(self):
        #SciPy align calculated positions with real positions
        
        #only use anchors
        anchor_nodes = [node for node in self.nodes.values() if node.tag == "anch"]
        
        # Build real and calculated matrices from nodes
        real = np.array([node.real for node in anchor_nodes])        # shape: (N_anchors, 2)
        calc = np.array([node.calculated for node in anchor_nodes])  # shape: (N_anchors, 2)
        
        # Compute centroids
        r_centroid = real.mean(axis=0)
        c_centroid = calc.mean(axis=0)
        
        # Center the coordinates
        R = real - r_centroid
        C = calc - c_centroid
        
        #RTC
        # Orthogonal Procrustes: find best rotation
        rotation, _ = orthogonal_procrustes(C, R)

        # Compute translation
        translation = r_centroid - c_centroid @ rotation

        # Apply transformation
        corrected = calc @ rotation + translation
        
        # Write back corrected positions to nodes
        for node, pos in zip(anchor_nodes, corrected):
            node.calculated = tuple(pos)
        
        # send updated positions to UI       
        self.send_UIData()
        
    def estimate_anchor_positions_scipy(self, dim=2):
        # Estimate anchor positions from pairwise distances using weighted nonlinear least squares.
        # magic happens here
        
        D, Sigma = self.build_matrices()
        
        N = D.shape[0]
        anchor_nodes = [node for node in self.nodes.values() if node.tag == "anch"] #List of only anchors for calculations

        # Initial guess: small random values
        x0 = np.random.randn(N*dim) * 0.1

        # Fix the first anchor (gauge)
        anchor0 = anchor_nodes[0].real

        # Create mask to fix anchor0
        def residuals(x):
            X = x.reshape(N, dim)
            res = []

            # Fix anchor 0
            X[0] = anchor0

            res = []
            for i in range(N):
                for j in range(i + 1, N):
                    if not np.isfinite(D[i, j]) or D[i, j] <= 0:
                        continue
                    dij = np.linalg.norm(X[i] - X[j])
                    weight = 1.0 / max(Sigma[i, j], 1e-8)
                    res.append(weight * (dij - D[i, j]))
            return np.array(res)

        result = least_squares(residuals, x0, verbose=2)

        positions = result.x.reshape(N, dim)
        # Ensure anchor0 is exactly fixed
        positions[0] = anchor0
        
        # Write results back into nodes
        for node, pos in zip(anchor_nodes, positions):
            node.calculated = tuple(pos)
            
        #correct the RTC of calculation
        self.Correction_pos()
        
    def filter_kalman(self, x, y):

        # first setup kalman
        if self.kf is None:
            kf = KalmanFilter(dim_x=4, dim_z=2)  # state: [x,y,vx,vy], meas: [x,y]
            kf.x = np.array([x, y, 0.0, 0.0], dtype=float)
            kf.H = np.array([[1, 0, 0, 0],[0, 1, 0, 0]], dtype=float) # means x and y relate to state x and y
            # [1x, 0y, 0vx, 0vy],[0x, 1y, 0vx, 0vy]

            kf.P = np.eye(4, dtype=float) * 1.0

            # Measurement noise needs to be set up 
            meas_std = 0.19
            kf.R = np.eye(2, dtype=float) * (meas_std ** 2)

            self.kf = kf
            self.kf_last_t = time.time()
            return (x, y)

        # time
        now = time.time()
        dt = now - self.kf_last_t
        self.kf_last_t = now

        # if timing goes bad
        dt = float(max(1e-3, min(0.5, dt)))

        self.kf.F = np.array([[1, 0, dt, 0],
                            [0, 1, 0, dt],
                            [0, 0, 1,  0],
                            [0, 0, 0,  1]], dtype=float)

        accel_std = 8.0  # m/s^2; can horse acelerate this fast?
        q = accel_std ** 2
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        self.kf.Q = q * np.array([[dt4/4, 0,     dt3/2, 0],
                             [0,     dt4/4, 0,     dt3/2],
                             [dt3/2, 0,     dt2,   0],
                             [0,     dt3/2, 0,     dt2]], dtype=float)

        z = np.array([x, y], dtype=float)

        self.kf.predict()
        self.kf.update(z)

        x_f = self.kf.x[0]
        y_f = self.kf.x[1]
        vx  = self.kf.x[2]
        vy  = self.kf.x[3]
        
        #for visualisation
        node = self.nodes.get("Kalman")
        node.calculated = (x_f, y_f)
        
        return (x_f, y_f)

    def append_csv_row(self, csv_path: str, row: dict):
        file_exists = os.path.exists(csv_path)
        fieldnames = list(row.keys())

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        
    def estimate_tag_position(self, dim=2):
        # Estimate tag position using known anchor locations.
        # magic also happens here
        
        tag_nodes = [node for node in self.nodes.values() if node.tag == "tag"]
        anchor_nodes = [node for node in self.nodes.values() if node.tag == "anch"]
        
        # Build anchor array
        anchors = np.array([node.calculated for node in anchor_nodes])  # shape: (N_anchors, dim)
        N_anchors = anchors.shape[0]
        
        for tag_node in tag_nodes:
            distances = np.array(tag_node.distance)  # shape: (N_anchors,)
            sigmas = np.array(tag_node.dispersion)
        
            # Initial guess: previous known location
            x0 = np.array(tag_node.calculated)
        
            # Residual function
            def residuals(x):
                res = []
                for i in range(N_anchors):
                    d = distances[i]
                    if not np.isfinite(d) or d <= 0:
                        continue
                    dij = np.linalg.norm(x - anchors[i])
                    weight = 1.0 / max(sigmas[i], 1e-8)
                    res.append(weight * (dij - distances[i]))
                return np.array(res)

            result = least_squares(residuals, x0, verbose=0, loss="soft_l1")
            
            # Save directly to node
            tag_node.calculated = tuple(result.x)
            
            x, y = result.x
            
            x_f, y_f = self.filter_kalman(x, y)
            
            x_real, y_real = tag_node.real
            self.diff += math.hypot(x_real - x, y_real - y)
            self.diff_k += math.hypot(x_real - x_f, y_real - y_f)
            
            
            
            if self.counter%5 == 0:
            
                row = {
                    "timestamp": time.time(),
                    "normal_diff": (self.diff/5),
                    "kalman_diff": (self.diff_k/5)
                }
                
                self.diff = 0
                self.diff_k = 0
                
                self.counter =0
                
                csv_path = f"tables/kalman/mesurments-kalman-diff.csv"
                self.append_csv_row(csv_path, row)
                
            self.counter += 1
            
            # send update to UI
            self.send_UIData()
            
            
            
            
    
    def send_UIData(self):
        payload = {"nodes": [asdict(node) for node in self.nodes.values()]}
        
        topic = f"hub/server/UIData"
        self.client.publish(topic, json.dumps(payload), qos=1)
    
    def handle_UIcommand(self, data):
        # command handeling
        command = data.get("command")
        
        print(f"executing command {command}")
        
        if command == "measure_anchors":
            self.measure_anchor()
        elif command == "measure_tags":
            self.measure_tag()
        elif command == "send_nodes":
            self.send_UIData()
        
if __name__ == "__main__":
    
    solver = Solver()
    solver.message_processor()