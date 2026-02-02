# threading and sync
import threading

# MQTT client for ESP32 communication
import paho.mqtt.client as mqtt

# messaging, command & data handling
from queue import Queue
import json

import random
import plotly.graph_objects as go
from nicegui import events, ui

import math


class WebUI:
    def __init__(self):
        self.BROKER_IP = "127.0.0.1"   #Mosquitto
        self.BROKER_PORT = 1883
        
        # MQTT Topics
        self.TOPIC = "hub/+/data"     
        self.TOPIC2 = "hub/+/command"     
        self.TOPIC3 = "hub/+/register"     
        self.TOPIC4 = "hub/+/UIData"
        self.TOPIC5 = "hub/+/UICommand"
        
        # MQTT client setup (version2)
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.BROKER_IP, self.BROKER_PORT, keepalive=60)
        self.client.loop_start()
        
        print("MQTT server running...")
        
        self.columns = []
        self.rows = []
        
        self.row_conf = []
        
        self.distance_table = []
        self.dispersion_table = []
        self.cord_table = []
        self.conf_table = []
        
        # data
        self.msg_queue = Queue()

        # figure + plot handle
        self.fig = go.Figure()
        self.fig.add_trace(go.Scatter(x=[], y=[], mode='markers', name='real'))
        self.fig.add_trace(go.Scatter(x=[], y=[], mode='markers', name='calculated', marker=dict(
            symbol='circle-open',  # empty circle
            color='red',
            size=10,
            line=dict(width=2)     # thickness of the circle
        )))
        self.fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), autosize=True)
        self.plot = None

        # build UI
        self._build_layout()

        
    def on_connect(self, client, userdata, flags, reason_code, properties):
        # MQTT on_connect callback
        if reason_code == 0:
            print("Connected to MQTT broker")
            self.client.subscribe(self.TOPIC4)
        else:
            print(f"Connection failed (reason_code={reason_code})")
    
    def add_node(self, data):
        nodes = data.get("nodes", {})
       
        # push into figure
        self.fig.data[0].x = [n["real"][0] for n in nodes]
        self.fig.data[0].y = [n["real"][1] for n in nodes]
        
        self.fig.data[1].x = [n["calculated"][0] for n in nodes]
        self.fig.data[1].y = [n["calculated"][1] for n in nodes]
        
        # refresh plotly element (uses existing fig reference)
        if self.plot is not None:
            self.plot.update()
        
        self.columns = []
        self.rows = []
        
        self.columns.append({
            'name': 'id',
            'label': 'Node',
            'field': 'id',
            'required': True,
            'align': 'left',
        })
        
        noc = len(nodes[0].get('distance', [])) #get the number of enteries in list
        
        for i in range(noc):
            name = f'esp32_{i}'
            self.columns.append({
                'name': name,
                'label': name,
                'field': name,
                'required': True,
                'align': 'left',
            })
            
        for idx, node in enumerate(nodes):
            row = {'id': f'esp32_{idx}'}

            distances = node.get('distance', [])
            for i, value in enumerate(distances):
                row[f'esp32_{i}'] = '' if i == idx else round(value, 3)

            self.rows.append(row)
            # if columns might change (node count changes), update them too
        self.distance_table.columns = self.columns

        # update rows
        self.distance_table.rows = self.rows

        # redraw
        self.distance_table.update()
            
        self.columns = []
        self.rows = []
        
        self.columns.append({
            'name': 'id',
            'label': 'Node',
            'field': 'id',
            'required': True,
            'align': 'left',
        })
        
        noc = len(nodes[0].get('dispersion', [])) #get the number of enteries in list
        
        for i in range(noc):
            name = f'esp32_{i}'
            self.columns.append({
                'name': name,
                'label': name,
                'field': name,
                'required': True,
                'align': 'left',
            })
            
        for idx, node in enumerate(nodes):
            row = {'id': f'esp32_{idx}'}

            distances = node.get('dispersion', [])
            for i, value in enumerate(distances):
                row[f'esp32_{i}'] = '' if i == idx else round(value, 3)

            self.rows.append(row)
            # if columns might change (node count changes), update them too
        self.dispersion_table.columns = self.columns

        # update rows
        self.dispersion_table.rows = self.rows

        # redraw
        self.dispersion_table.update()
            
        
        col = [{'name': 'id', 'label': 'Node', 'field': 'id', 'required': True, 'align': 'left'},
        {'name': 'Rx', 'label': 'Rx', 'field': 'Rx', 'required': True, 'align': 'left'},
        {'name': 'Ry', 'label': 'Ry', 'field': 'Ry', 'required': True, 'align': 'left'},
        {'name': 'Cx', 'label': 'Cx', 'field': 'Cx', 'required': True, 'align': 'left'},
        {'name': 'Cy', 'label': 'Cy', 'field': 'Cy', 'required': True, 'align': 'left'},
        {'name': 'Diff', 'label': 'Diff', 'field': 'Diff', 'required': True, 'align': 'left'}]
        row = []
        
        
        for node in nodes:
            Rx, Ry = node["real"]
            Cx, Cy = node["calculated"]
            
            diff = math.hypot(Cx - Rx, Cy - Ry)
            
            row.append({
                'id': node["id"],
                'Rx': round(Rx, 2),
                'Ry': round(Ry, 2),
                'Cx': round(Cx, 2),
                'Cy': round(Cy, 2),
                'Diff': round(diff, 2),  # optional rounding for UI
            })
            
        
        self.cord_table.columns = col

        # update rows
        self.cord_table.rows = row

        # redraw
        self.cord_table.update()
        
                    
        #self.msg_queue.put((topic_parts[1], topic_parts[2], payload))
        
    def add_config(self, data):
        
        nodes = data.get("nodes", {})
        self.row_conf = []
        i = 0
        
        for node in nodes:
            print(f"adding esp config: {node.get('id')}, {node.get('tag')}, {node.get('x')}, {node.get('y')}")
            
            
            
            real = node.get("real")
            x = real[0]
            y = real[1]
            
            self.row_conf.append({'id': i, 'ID': node.get('id'), 'Tag': node.get('tag'), 'X': x, 'Y': y})
            i = i + 1
            
        # update rows
        self.conf_table.rows = self.row_conf

        # redraw
        self.conf_table.update()
        
    def on_message(self, client, userdata, msg):
        # MQTT on_message callback
        # queue to separate network from data processing
        try:
            print("handeling on message")
            topic_parts = msg.topic.split("/")
            payload = json.loads(msg.payload.decode("utf-8"))
            
            sorce = topic_parts[1]
            
            if sorce == "server":
                self.add_node(payload)
            elif sorce == "ESP32_Manager":
                self.add_config(payload)
        except Exception as e:
            print("Error processing message:", e)

    def _build_layout(self) -> None:
        with ui.header().classes(replace='row items-center'):
            ui.button(on_click=lambda: self.left_drawer.toggle(), icon='menu').props('flat color=white')
            with ui.tabs() as self.tabs:
                ui.tab('A')
                ui.tab('B')
                ui.tab('C')

        with ui.footer(value=False) as self.footer:
            ui.label('Footer')

        with ui.left_drawer().classes('bg-blue-100') as self.left_drawer:
            ui.label('Side menu')

        with ui.page_sticky(position='bottom-right', x_offset=100, y_offset=20):
            ui.button(on_click=self.footer.toggle, icon='contact_support').props('fab')

        with ui.tab_panels(self.tabs, value='A').classes('w-full h-full'):
            with ui.tab_panel('A'):
                with ui.row().classes('w-full h-full gap-4'):
                    with ui.column().style('flex: 2;'):
                        ui.label('Positioning graph')
                        self.plot = ui.plotly(self.fig).style(
                            'width:700px; height:700px; resize:both; overflow:auto'
                        )
                        
                    with ui.column().style('flex: 1;'):
                        with ui.row().classes('gap-2'):
                            ui.button("measure_anchors", on_click=lambda: self.send_message("measure_anchors","solver"))
                            ui.button("measure_tags", on_click=lambda: self.send_message("measure_tags","solver"))
                            ui.button("send_nodes", on_click=lambda: self.send_message("send_nodes","solver"))
                        
                        self.distance_table = ui.table(columns=self.columns, rows=self.rows, row_key='id')
                        self.distance_table.props('dense')
                        
                        self.dispersion_table = ui.table(columns=self.columns, rows=self.rows, row_key='id')
                        self.dispersion_table.props('dense')
                        
                        self.cord_table = ui.table(columns=[], rows=[], row_key='id')
                        self.cord_table.props('dense')

            with ui.tab_panel('B'):
                ui.label('Content of B')
                ui.button("add_ESP32", on_click=lambda: self.send_message("add_ESP32","ESP32_Manager"))
                ui.button("get_Data", on_click=lambda: self.send_message("send_nodes","ESP32_Manager"))
                
                columns = [
                    {'name': 'ID', 'label': 'ID', 'field': 'ID'},
                    {'name': 'Tag', 'label': 'Tag', 'field': 'Tag'},
                    {'name': 'X', 'label': 'X', 'field': 'X'},
                    {'name': 'Y', 'label': 'Y', 'field': 'Y'},
                    {'name': 'action', 'label': 'Action'},
                ]
                self.row_conf = [
                    {'id': 0, 'ID': 'asds1d68sa7d3', 'Tag': 'NotSet', 'X': '0', 'Y': '0'},
                    {'id': 1, 'ID': 'fgh8dsa3f5awd', 'Tag': 'NotSet', 'X': '0', 'Y': '0'},
                    {'id': 2, 'ID': 'prun28f4q96f1', 'Tag': 'NotSet', 'X': '0', 'Y': '0'},
                ]
                name_options = ['anch', 'tag']
                
                

                def rename(e: events.GenericEventArguments) -> None:
                    row_id, name_index = e.args
                    for row in self.conf_table.rows:
                        if row['id'] == row_id:
                            row['Tag'] = name_options[name_index]

                self.conf_table = ui.table(columns=columns, rows=self.row_conf).classes('w-full')
                
                with self.conf_table.add_slot('body-cell-Tag'):
                    with self.conf_table.cell('Tag'):
                        ui.select(name_options).props(':model-value=props.row.Tag').on(
                            'update:model-value',
                            js_handler='(e) => emit(props.row.id, e.value)',
                            handler=rename,
                        )

                def update_x(e):
                    row_id, value = e.args
                    for row in self.conf_table.rows:
                        if row['id'] == row_id:
                            row['X'] = value
                            break
                           
                def update_y(e):
                    row_id, value = e.args
                    for row in self.conf_table.rows:
                        if row['id'] == row_id:
                            row['Y'] = value
                            break
                
                with self.conf_table.add_slot('body-cell-X'):
                    with self.conf_table.cell('X'):
                        ui.number(format='%.2f').props(':model-value=props.row.X').on('update:model-value', js_handler='(v) => { props.row.X = v; emit(props.row.id, v); }', handler=update_x,)
                        
                with self.conf_table.add_slot('body-cell-Y'):
                    with self.conf_table.cell('Y'):
                        ui.number(format='%.2f').props(':model-value=props.row.Y').on('update:model-value', js_handler='(v) => { props.row.Y = v; emit(props.row.id, v); }', handler=update_y,)
                
                def send_conf(e):
                    row_id = e.args
                    row = next(r for r in self.conf_table.rows if r['id'] == row_id)

                    print('APPLY:', row)     

                    payload = {
                        "type": "final_config",
                        "id": row.get('ID'),
                        "tag": row.get('Tag'),
                        "x": row.get('X'),
                        "y": row.get('Y'),
                    }
                    
                    topic = f"hub/{row.get('ID')}/command"
        
                    print(f"sending data to {topic}")
                    
                    self.client.publish(topic, json.dumps(payload), qos=1)
                        
                with self.conf_table.add_slot('body-cell-action'):
                    with self.conf_table.cell('action'):
                        ui.button('Apply').props('flat').on(
                            'click',
                            js_handler='() => emit(props.row.id)',
                            handler=send_conf,
                        )

            with ui.tab_panel('C'):
                ui.label('Content of C')
                
    def send_message(self, message, type):
        payload = {"command": message}
        
        topic = f"hub/{type}/UICommand"
        self.client.publish(topic, json.dumps(payload), qos=1)

web = WebUI()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(host='0.0.0.0', port=8080)