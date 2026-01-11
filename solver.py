#holy import
from flask import Flask, request, jsonify
import threading
import requests
import time
import tkinter as tk
import random
import cvxpy as cp
import numpy as np
from scipy.optimize import least_squares
from scipy.linalg import orthogonal_procrustes
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from queue import Queue
from WebUi import WebUI
import json
import paho.mqtt.client as mqtt
from datetime import datetime

class ConfigServer:
    def __init__(self, data_queue):
        #move this to config file and remove all that i nolonger in use
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        self.TOPIC = "hub/+/data"     
        self.TOPIC2 = "hub/+/command"     
        self.TOPIC3 = "hub/+/register"     
        
        self.data = ""
        self.in_topic = ""
        self.processed = True
        self.Hold = False
        self.first_run = False
        
        self.app = Flask(__name__)
        self.clients = [] # List to store connected clients
        self.tags = [] # List to store tag clients
        self.next_id = 1 
        self.last_result = None
        self.result_received = False
        self.data_queue = data_queue

        self.distance_matrix = []
        self.dispersion_matrix = []
        self.list_tag_dis = []
        self.list_tag_disp = []
        
        self.Real_x_Data = []
        self.Real_y_Data = []
        self.calculated_x_Data = []
        self.calculated_y_Data = []
        
        # Start console input thread
        thread = threading.Thread(target=self.console_loop, daemon=True)
        thread.start()
        
        # Start message_processor thread
        thread = threading.Thread(target=self.message_processor, daemon=True)
        thread.start()
        
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.client.connect(self.BROKER_IP, self.BROKER_PORT, keepalive=60)
        self.client.loop_forever()

        print("MQTT server running...")
        

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT broker")
            self.client.subscribe(self.TOPIC)
            self.client.subscribe(self.TOPIC3)
        else:
            print(f"Connection failed (rc={rc})")
        
    def on_message(self, client, userdata, msg):
        try:
            esp_id = msg.topic.split("/")[1]

            payload = msg.payload.decode("utf-8")
            self.in_topic = msg.topic.split("/")[2]
            self.data = json.loads(payload)
            self.result_received = True
        except Exception as e:
            print("Error processing message:", e)
            
    def message_processor(self):
        while True:
            if not self.result_received:
                time.sleep(0.01)
                continue

            if self.in_topic == "register":
                self.register_client()
            elif self.in_topic == "data":
                if self.data.get("tag") == "anch":
                    self.receive_result()
                elif self.data.get("tag") == "tag":
                    self.process_tag()
                else:
                    tag = self.data.get("tag")
                    print(f"unknown tag: {tag}")
            else:
                print(f"unknown topic: {self.in_topic}")
            self.data = None
            self.result_received = False

    def register_client(self):
        
        client_info = {
            "id": self.data.get('esp_id'),
            "tag": self.data.get('tag'),
            "x": self.data.get('x'),
            "y": self.data.get('y')
        }
            
        client_tag = client_info.get('tag')
            
        if client_tag == "anch":
            self.clients.append(client_info)
        elif client_tag == "tag":
            self.tags.append(client_info)
            
        self.Real_x_Data.append(client_info.get('x'))
        self.Real_y_Data.append(client_info.get('y'))
            
        self.data_queue.put((self.Real_x_Data, self.Real_y_Data, self.calculated_x_Data, self.calculated_y_Data))
            
        self.next_id += 1
        print(
            f"[SERVER] Registered client: "
            f"{client_info['id']} | "
            f"{client_info['tag']} | "
            f"{client_info['x']:.2f}/"
            f"{client_info['y']:.2f}"
        )
    
    def receive_result(self):
        # Initialize matrices if they don't exist
        if not hasattr(self, 'distance_matrix'):
            self.distance_matrix = []  # Stores list_a from clients
        if not hasattr(self, 'dispersion_matrix'):
            self.dispersion_matrix = []  # Stores list_b from clients

        # Append the received data as a new row (why am I rounding it to 2 places?)
        self.distance_matrix.append([round(x, 2) for x in self.data.get('list_a', [])])
        self.dispersion_matrix.append([round(x, 2) for x in self.data.get('list_b', [])])
        
        self.Hold = False

    def measure_all(self):
        print("[SERVER] Starting measurements...")

        for client in self.clients:
            print(f"\n[SERVER] Sending measurement command to client: {client['id']}...")
            
            self.Hold = True

            payload = {
                "command": "start_measurement"
            }
            
            client_id = client['id']
            topic = f"hub/{client_id}/command"
            self.client.publish(topic, json.dumps(payload), qos=1)
            
            while self.Hold:
                time.sleep(0.05)

    def process_tag(self):
        print("[SERVER] Received tag_positioning:", self.data)

        self.list_tag_dis = self.data.get('list_a', [])
        self.list_tag_disp = self.data.get('list_b', [])
        
        self.Real_x_Data[-1] = self.data.get('x')
        self.Real_y_Data[-1] = self.data.get('y')
        
        tag_pos = self.estimate_tag_position(
            tag_distances=np.array(self.list_tag_dis),
            sigma=np.array(self.list_tag_disp),
            dim=2
        )
        
        if self.first_run == False:
            self.calculated_x_Data.append(tag_pos [0])
            self.calculated_y_Data.append(tag_pos [1])
            self.first_run = True
        else:
            self.calculated_x_Data[-1] = tag_pos [0]
            self.calculated_y_Data[-1] = tag_pos [1]
                
        self.data_queue.put((self.Real_x_Data, self.Real_y_Data, self.calculated_x_Data, self.calculated_y_Data))
        

    def print_matrix(self, matrix, name="Matrix"):
        if not matrix:
            print(f"[SERVER] {name} is empty.")
            return

        num_rows = len(matrix)
        num_cols = len(matrix[0])

        header = "     " + "  ".join(f"{col+1:>5}" for col in range(num_cols))
        print(f"[SERVER] {name}:")
        print(header)
        print("    " + "-" * (num_cols * 6))

        for row_idx, row in enumerate(matrix, start=1):
            row_str = "  ".join(f"{val:>5.2f}" for val in row)  # rounded to 2 decimals
            print(f"{row_idx:>3} | {row_str}")
    
    #using scipy orthogonal_procrustes automaticali correct rotation and translation of calculated data
    def Correction_pos(self): 
        real = np.column_stack((self.Real_x_Data, self.Real_y_Data))
        calc = np.column_stack((self.calculated_x_Data, self.calculated_y_Data))
        
        #removing tag from real data
        real = real[:-1]
        
        r_centroid = real.mean(axis=0)
        c_centroid = calc.mean(axis=0)
        
        R = real - r_centroid
        C = calc - c_centroid
        
        rotation, _ = orthogonal_procrustes(C, R)
        translation = r_centroid - c_centroid @ rotation
        
        corrected = calc @ rotation + translation
        
        self.calculated_x_Data = corrected[:, 0].tolist()
        self.calculated_y_Data = corrected[:, 1].tolist()
        
    def estimate_anchor_positions_scipy(self, D, Sigma, dim=2):
        #dont ask i dont know but it works
        
        """
        Estimate anchor positions from pairwise distances using SciPy nonlinear least squares.

        Parameters
        ----------
        D : NxN numpy array
            Distance matrix
        Sigma : NxN numpy array
            Variance (dispersion) matrix
        Real_x_Data, Real_y_Data : arrays
            Coordinates for gauge fixing (anchor 0)
        dim : int
            Dimension (2 or 3)

        Returns
        -------
        positions : Nx(dim) numpy array
        """

        N = D.shape[0]

        # Initial guess: small random values
        x0 = np.random.randn(N*dim) * 0.1

        # Fix the first anchor (gauge)
        anchor0_x = self.Real_x_Data[0]
        anchor0_y = self.Real_y_Data[0]

        # Create mask to fix anchor0
        def residuals(x):
            X = x.reshape(N, dim)
            res = []

            # Fix anchor 0
            X[0,0] = anchor0_x
            X[0,1] = anchor0_y

            for i in range(N):
                for j in range(i+1, N):
                    if not np.isfinite(D[i,j]) or D[i,j] <= 0:
                        continue
                    dij = np.linalg.norm(X[i] - X[j])
                    weight = 1.0 / max(Sigma[i,j], 1e-8)
                    res.append(weight * (dij - D[i,j]))
            return np.array(res)

        result = least_squares(residuals, x0, verbose=2)

        positions = result.x.reshape(N, dim)
        # Ensure anchor0 is exactly fixed
        positions[0,0] = anchor0_x
        positions[0,1] = anchor0_y
        
        

        return positions  
        
    def estimate_tag_position(self, tag_distances, sigma=None, dim=2):
        #dont ask i dont know but it works
        
        """
        Estimate the position of a moving tag given distances to fixed anchors.
        
        Parameters
        ----------
        tag_distances : array-like, shape (N,)
            Distances from the tag to each anchor.
        anchors : array-like, shape (N, dim)
            Coordinates of the anchors.
        sigma : array-like, shape (N,), optional
            Standard deviations of the distance measurements (for weighting).
        dim : int
            Spatial dimension (2 or 3)
        
        Returns
        -------
        tag_pos : array, shape (dim,)
            Estimated tag position.
        """
        
        anchors = np.column_stack((
            self.calculated_x_Data[:-1],
            self.calculated_y_Data[:-1]
        ))
        
        N = anchors.shape[0]
        sigma = np.ones(N) if sigma is None else np.array(sigma)
        
        # Initial guess: centroid of anchors
        x0 = anchors.mean(axis=0)

        def residuals(x):
            res = []
            for i in range(N):
                if not np.isfinite(tag_distances[i]) or tag_distances[i] <= 0:
                    continue
                dij = np.linalg.norm(x - anchors[i])
                weight = 1.0 / max(sigma[i], 1e-8)
                res.append(weight * (dij - tag_distances[i]))
            return np.array(res)

        result = least_squares(residuals, x0, verbose=0)
        return result.x
        

    def console_loop(self):
        while True:
            cmd = input("> ").strip().lower()

            if cmd == "print":
                if not self.clients:
                    print("[SERVER] No clients registered.")
                    continue

                print(f"{'client':<8} | {'id':<4} | {'ip':<15} | {'port':<5}")
                print("-" * 50)

                for index, client in enumerate(self.clients, start=1):
                    print(
                        f"{index:<8} | "
                        f"{client['id']:<4} | "
                        f"{client['ip']:<15} | "
                        f"{client['port']:<5}"
                    )

            elif cmd == "measure":
                self.measure_all()

            elif cmd == "measurement": 
                self.print_matrix(self.distance_matrix, "Distance Matrix")
                self.print_matrix(self.dispersion_matrix, "Dispersion Matrix")
            elif cmd == "calculate":
                D = np.array(self.distance_matrix)
                Sigma = np.array(self.dispersion_matrix)
                positions = self.estimate_anchor_positions_scipy(D, Sigma)
                print("Estimated positions:\n", positions)
                for pos in positions:
                    self.calculated_x_Data.append(pos[0])
                    self.calculated_y_Data.append(pos[1])
                self.Correction_pos()
                self.data_queue.put((self.Real_x_Data, self.Real_y_Data, self.calculated_x_Data, self.calculated_y_Data))
            elif cmd == "locate":
                print("[SERVER] Starting tag...")

                client = self.tags[0]
                payload = {
                    "command": "start_tag"
                }
                
                client_id = client['id']
                topic = f"hub/{client_id}/command"
                self.client.publish(topic, json.dumps(payload), qos=1)
                    
            else:
                print("Unknown command. Use: print | measure")

    def run(self, host='0.0.0.0', port=5050):
        self.app.run(host=host, port=port)

if __name__ == '__main__':
    
    data_queue = Queue()
    
    def run_gui():
        # Create the UI instance
        ui = WebUI(data_queue)
        # Launch the web interface
        ui.launch()
        
    gui_thread = threading.Thread(target=run_gui, daemon=True)
    gui_thread.start()
    
    server = ConfigServer(data_queue)
    server.run()