import logging
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
        
        self.logger = logging.getself.logger()
        self.logger.setLevel(logging.INFO)

        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        console = logging.StreamHandler()
        console.setFormatter(formatter)

        file = logging.FileHandler("Solver.log")
        file.setFormatter(formatter)

        self.self.logger.addHandler(console)
        self.logger.addHandler(file)
        
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
        
#====================================================================================
#            comms basic section (mqtt)
#==================================================================================== 
    def on_connect(self, client, userdata, flags, reason_code, properties):
        # MQTT on_connect callback
        if reason_code == 0:
            self.logger.info("Connected to MQTT broker")
            self.client.subscribe("hub/solver/cmd/measure_anchor")
            self.client.subscribe("hub/solver/cmd/toggle_tag_ranging")
            self.client.subscribe("hub/solver/cmd/toggle_tag_sim")
            self.client.subscribe("hub/esp/+/ranging")
            self.client.subscribe("hub/esp/+/status")
        else:
            self.logger.error(f"Connection failed (reason_code={reason_code})")
        
    def on_message(self, client, userdata, msg):
        # MQTT on_message callback
        # queue to separate network from data processing
        try:
            topic_parts = msg.topic.split("/")
            payload = json.loads(msg.payload.decode("utf-8"))
            self.msg_queue.put((topic_parts, payload))
        except Exception as e:
            self.logger.error("Error processing message: %s", e)

    def message_processor(self):
        # processes MQTT messages
        while True:
            topic_parts, data = self.msg_queue.get()  # blocks until message is available

            if topic_parts[1] == "solver":
                if topic_parts[3] == "measure_anchor":
                    threading.Thread(target=self.measure, args=("anch",), daemon=True).start()
                elif topic_parts[3] == "toggle_tag_ranging":
                    threading.Thread(target=self.measure, args=("tag",), daemon=True).start()
                elif topic_parts[3] == "toggle_tag_sim":
                    topic = f"hub/esp/bcast/cmd/move"
                    self.client.publish(topic, "", qos=1)
                else:
                    self.logger.error(f"Error processing command: {topic_parts[3]}")
            elif topic_parts[1] == "esp":
                if topic_parts[3] == "ranging":
                    self.process_ranging(data)
                elif topic_parts[3] == "status":
                    self.update_node(data)
                else:
                    self.logger.error(f"Error processing esp data: {topic_parts[3]}")
            else:
                self.logger.error(f"Error processing topic: {topic_parts}")
#====================================================================================
#            comms section (mqtt)
#==================================================================================== 
    def send_UIData(self):
        payload = {"nodes": [asdict(node) for node in self.nodes.values()]}
        
        topic = f"hub/solver/solution"
        self.client.publish(topic, json.dumps(payload), retain=True, qos=1)
        
    def update_node(self, data):
        node_id = data.get("esp_id")
        tag = data.get("tag")
        real = data.get("cords")
        
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.tag = tag
            node.real = real
        else: 
            self.nodes[node_id] = Nodes(node_id, tag, real)
            
        self.send_UIData()
    
    def process_ranging(self, data):
        node = self.nodes.get(data.get("esp_id"))
        
        node.distance = data.get("mean_distances")
        node.dispersion = data.get("std_deviations")
        
        if data.get("tag") == "tag":
            node.real = data.get("cords")
            node = self.nodes.setdefault("Kalman", Nodes("Kalman", "tag", data.get("cords")))
            node.real = data.get("cords")
            self.estimate_tag_position()
            
        self.measurement_done.set()
        
    def measure(self, tag):
        self.logger.info("[SERVER] Starting measurements...")
        
        nodes = [node for node in self.nodes.values() if node.tag == tag]
        
        for node in nodes:
            self.logger.info(f"\n[SERVER] Sending measurement command to client: {node.id}...")
            
            topic = f"hub/esp/{node.id}/measure"
            self.client.publish(topic, "", qos=1)
            self.measurement_done.clear()
            
            # Wait until ESP returns data or 1:30 min passes
            finished = self.measurement_done.wait(timeout=90)
            
            if not finished:
                self.logger.error(f"[SERVER] Failed to receive data from node: {node.id}")  
                
        if tag == "anch":        
            self.estimate_anchor_positions_scipy()
        else:
            #add one time visual ndoe
            self.estimate_tag_position()

#====================================================================================
#            filters and estimation section
#====================================================================================  
    def build_matrices(self):
        # build matrix for anchors to be used in position estimation
        anchor_nodes = [node for node in self.nodes.values() if node.tag == "anch"]
        
        print(anchor_nodes)

        distance_matrix = [node.distance for node in anchor_nodes]
        dispersion_matrix = [node.dispersion for node in anchor_nodes]

        return np.array(distance_matrix), np.array(dispersion_matrix)
    
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
            
            self.counter += 1
            
            # send update to UI
            self.send_UIData()
            
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

        accel_std = 3.0  # m/s^2; can horse acelerate this fast?
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

        
        
if __name__ == "__main__":
    
    solver = Solver()
    solver.message_processor()