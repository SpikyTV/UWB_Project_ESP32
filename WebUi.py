#imports pleanty of imports
import matplotlib.pyplot as plt
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from queue import Queue

#WebUI that is not running on web why?
class WebUI:
    def __init__(self, data_queue):
        self.data_queue = data_queue
        self.root = tk.Tk()
        self.root.title("tracker")

        # Matplotlib figure
        self.fig = plt.Figure(figsize=(5, 4))
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlim(-2, 22)
        self.ax.set_ylim(-2, 22)
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack()

        # Start update loop
        self.update_plot()

    def update_plot(self):
        while not self.data_queue.empty():
            # Get latest data
            x_data, y_data, x2_data, y2_data = self.data_queue.get()

            self.ax.clear()
            self.ax.grid(True)

            # Real position blue dots
            self.ax.scatter(x_data, y_data, color='blue', label='real', s=50)

            # calculated position red circles
            self.ax.scatter(x2_data, y2_data, facecolors='none', edgecolors='red', s=80, label='calc')
    

            self.ax.set_xlim(-2, 22)
            self.ax.set_ylim(-2, 22)
            self.ax.set_xlabel("X axis")
            self.ax.set_ylabel("Y axis")
            self.ax.set_title("Anch pos")
            self.ax.legend()

        self.canvas.draw()
        self.root.after(10, self.update_plot)  # refresh every 10ms

    def launch(self):
        self.root.mainloop()