import random
import time
import math

#running value calculatin is in ESP32 now
class Stats:
    def __init__(self, start_samples=20, max_error=0.5, true_distance=10.0):
        self.true_distance = true_distance

# ---------------------------
# Distance generator function
# ---------------------------
def generate_distance(true_distance=10.0, std_dev=0.30):
    
    # chance of random big error
    if random.random() < 0.02:
        return true_distance + random.uniform(0.5, 3.0)
    
    # normal mesurment
    u1 = random.random()
    u2 = random.random()
    z = (-2 * math.log(u1)) ** 0.5 * math.cos(2 * math.pi * u2)
    return true_distance + z * std_dev
