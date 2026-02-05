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
def generate_distance(real_distance, standard_diviation=0.3):
    #generate  random intiger divide by max intiger offset to +- 0.5 multiply by standard diviation
    #default 0.3 (+- 30cm should be standard for real uwb)
    noise = random.uniform(-standard_diviation, standard_diviation)
        
    #small chance for error data (1 in 100)
    #will add 0.5 to 3 meters
    if random.random() < 0.01:
        noise += random.uniform(0.5, 3)
        
    return real_distance + noise
