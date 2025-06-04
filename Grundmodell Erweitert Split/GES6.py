# Standardbibliothek
import random
import math
import time
import ctypes
import multiprocessing
from multiprocessing import Queue, Process
from functools import partial
import tkinter as tk
from tkinter import ttk

# Drittanbieter
import matplotlib
import matplotlib.pyplot as plt
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg

# Panda3D und Direct (Engine-spezifische Importe)
from panda3d.core import (
    LColor,
    GeomVertexFormat,
    GeomVertexData,
    GeomVertexWriter,
    GeomLines,
    GeomTriangles,
    Geom,
    GeomNode,
    ClockObject,
    AmbientLight,
    DirectionalLight,
    Vec2,
    Vec3,
    LineSegs,
    TextNode,
    CardMaker,
    NodePath,
    RenderModeAttrib
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.task.TaskManagerGlobal import taskMgr
from direct.gui.DirectGui import DirectButton, DirectSlider, DirectLabel

from direct.showbase.ShowBase import ShowBase
from environment_visualization import EnvironmentVisualizer

class LagerSimulation(ShowBase):
    def __init__(self, graph_queue=None):
        # Basisinitialisierung (ShowBase, etc.)
        super().__init__()

        # ------------------------------------------------------------------------
        # 1. Umgebung aufbauen: Verwende den extrahierten EnvironmentVisualizer
        # ------------------------------------------------------------------------
        self.env_viz = EnvironmentVisualizer(self.render, self.loader)

        # Rufe die Methoden des Visualizers auf, um die Umgebung zu erstellen.
        self.env_viz.draw_origin()
        self.env_viz.erzeuge_licht()
        self.env_viz.erzeuge_bodenraster(center_extent=70, cell_size=1)
        self.env_viz.create_wall()
        self.env_viz.create_annahme_stations()
        self.env_viz.create_abgabe_stations()
        self.env_viz.create_garagen_stations()

        # Um in anderen Methoden (z. B. für Paket- oder Auftrags-Handling) auf die Stationen
        # und deren Marker zugreifen zu können, übergeben wir die entsprechenden Listen.
        self.annahme_stations = self.env_viz.annahme_stations
        self.station_blue_dots = self.env_viz.station_blue_dots
        self.abgabe_stations = self.env_viz.abgabe_stations
        self.abgabe_blue_dots = self.env_viz.abgabe_blue_dots
        self.garagen_stations = self.env_viz.garagen_stations
        self.garagen_parking_points = self.env_viz.garagen_parking_points

        # Setze den Pickup-Offset (dieser Vektor wird bei der Steuerung genutzt)
        self.pickup_offset = Vec3(0.5, -0.5, 0)

        # Falls du weitere Referenzen (wie self.blue_dot, self.station_green_dot) brauchst, ebenfalls setzen.
        if hasattr(self.env_viz, 'blue_dot'):
            self.blue_dot = self.env_viz.blue_dot
        if hasattr(self.env_viz, 'station_green_dot'):
            self.station_green_dot = self.env_viz.station_green_dot

        # ------------------------------------------------------------------------
        # 2. Restliche Initialisierung (Simulationsvariablen, UI, Tasks, etc.)
        # (Der restliche Code bleibt weitgehend unverändert.)
        # ------------------------------------------------------------------------

        self.paused = False
        self.sim_clock = 0.0
        self.speed_factor = 1.0
        self.current_speed = 1.5

        # Weitere Attribute, z. B. für KPIs, Paket- und Auftragsverwaltung usw.
        self.delivered_packages = 0
        self.pickup_packages = {}
        self.last_removed = {}
        self.orders = {}
        self.orders_queue = []
        self.next_order_id = 1
        # (Weitere Initialisierungen kommen hier…)
        self.cargos = {}
        # Falls du auch weitere Attribute benötigst, wie beispielsweise eine Liste der belegten Pickup-Stations:
        self.occupied_pickups = set()

        self.max_overall_wait_time = 0.0  # Maximale Wartezeit der Pakete
        self.total_dwell_time = 0.0  # Summe aller Liegedauern abgeholter Pakete
        self.picked_up_count = 0  # Anzahl abgeholter Pakete
        self.total_delivery_time = 0.0  # Summe aller Lieferzeiten
        self.total_delivery_count = 0  # Anzahl der Lieferungen
        self.max_overall_delivery_time = 0.0

        self.graph_queue = None
        self.graph_data = []
        self.graph_process = None

        # Beispiel: Initialisierung des Tkinter-Fensters
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()

        # Weiterer Code: Kamera, Lichter (falls weiterhin benötigt – ansonsten übernehmen wir vollständig den Visualizer)
        self.cam.setPos(11, -80, 40)
        self.cam.lookAt(11, 30, 0)

        # UI-bezogene Attribute initialisieren:
        self.order_win = None
        self.order_tree = None
        self.graph_queue = None
        self.graph_data = []

        # TensorFlow-Modell und RL-Agent initialisieren (wie gehabt)
        try:
            import tensorflow as tf
            self.tf_model = tf.keras.models.load_model("mein_model.keras")
            print("TensorFlow Modell erfolgreich geladen.")
        except Exception as e:
            print(f"Fehler beim Laden des TensorFlow Modells: {e}")
            self.tf_model = None

        state_bins = ((10, 10), (10, 10))
        action_space = [0, 1, 2]
        self.rl_agent = RLAgent(state_bins, action_space, learning_rate=0.1, discount_factor=0.9, epsilon=0.2)
        self.training_data = []  # Trainingsdatenliste

        # Spawn-Einstellungen (Standardwerte)
        self.package_spawn_delay = 5.0
        self.package_spawn_distribution = "uniform"
        # Hier speichern wir die Variablen für die Stationen als Dictionary (Index -> BooleanVar)
        self.spawn_station_vars = {}
        # Falls du beispielsweise 10 Annahmestationen hast:
        for i in range(10):
            self.spawn_station_vars[i] = tk.BooleanVar(value=False)

        # Fahrzeuge in den Garagen instanziieren:
        self.create_garage_vehicles()
        # --- UI-Elemente für Simulationssteuerung ---
        # Slider für Simulationsgeschwindigkeit
        # UI – Slider und Info-Anzeige
        self.speed_slider = DirectSlider(
            range=(0.1, 10.0),
            value=self.speed_factor,
            pageSize=0.1,
            command=self.update_simulation_speed,
            pos=(0, 0, -0.85),
            scale=0.3
        )
        self.speed_label = DirectLabel(
            text=f"Sim Time Factor: {self.speed_factor:.1f}",
            pos=(0, 0, -0.75),
            scale=0.07
        )
        self.info_label = DirectLabel(
            text="Laufzeit: 0.0s",
            pos=(1.2, 0, 0.8),
            scale=0.07,
            frameColor=(0, 0, 0, 0)
        )

        self.paused = False
        # Pause-Knopf neben dem Slider platzieren – z.B. rechts davon.
        self.pause_button = DirectButton(
            text="Pause",
            command=self.toggle_pause,
            pos=(-0.5, 0, -0.85),  # Leicht links vom Slider
            scale=0.07
        )

        # --- Tastenzuordnungen ---
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)
        self.accept("g", self.open_graph)
        self.accept("a", self.show_order_list)
        self.accept("d", self.deliver_first_order)
        # Taste "c" öffnet das Fahrzeug-Kontrollfenster
        self.accept("c", self.show_vehicle_control)

        # --- Tasks (TaskMgr) hinzufügen ---
        self.taskMgr.add(self._tk_update, "tkUpdateTask")
        self.taskMgr.add(self.update_delivery_timers, "UpdateDeliveryTimersTask")
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClock")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        self.taskMgr.add(self.update_graph_data, "UpdateGraphDataTask")
        self.taskMgr.add(self.check_and_spawn_packages, "CheckSpawnPackagesTask")
        self.taskMgr.add(self.update_package_timers, "UpdatePackageTimersTask")
        self.taskMgr.add(self.update_order_status, "UpdateOrderStatusTask")
    # ---------------1. Initialisierung & Simulationssteuerung---------------
    def update_sim_clock(self, task):
        dt = ClockObject.getGlobalClock().getDt() * self.speed_factor
        self.sim_clock += dt
        return Task.cont

    def toggle_pause(self):
        if not self.paused:
            # Speichern des aktuellen speed_factor, damit wir ihn beim Resume wiederherstellen können
            self.previous_speed_factor = self.speed_factor
            self.speed_factor = 0  # Simulation einfrieren: alle dt-basierte Updates ergeben 0
            self.pause_button['text'] = "Weiter"
            self.paused = True
            print("Gesamte Simulation angehalten")
        else:
            # Wiederaufnahme der Simulation: speed_factor auf den vorherigen Wert zurücksetzen
            self.speed_factor = self.previous_speed_factor if hasattr(self, 'previous_speed_factor') else 1.0
            self.pause_button['text'] = "Pause"
            self.paused = False
            print("Simulation läuft wieder")

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def zoom_in(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = max(10, current_fov - 5)
        lens.setFov(new_fov)
        print(f"Zoom In: FOV von {current_fov} auf {new_fov}")

    def zoom_out(self):
        lens = self.cam.node().getLens()
        current_fov = lens.getFov()[0]
        new_fov = min(100, current_fov + 5)
        lens.setFov(new_fov)
        print(f"Zoom Out: FOV von {current_fov} auf {new_fov}")

    def update_vehicle(self, task):
        # dt jetzt skaliert mit der Simulationsgeschwindigkeit
        dt = ClockObject.getGlobalClock().getDt() * self.speed_factor
        pos = self.vehicle.getPos()
        forward = self.vehicle.getQuat().getForward()

        target_speed = 1.5
        acc_rate = 2.0

        if self.current_speed < target_speed:
            self.current_speed = min(self.current_speed + acc_rate * dt, target_speed)
        elif self.current_speed > target_speed:
            self.current_speed = max(self.current_speed - acc_rate * dt, target_speed)

        new_pos = pos + forward * self.current_speed * dt
        self.vehicle.setPos(new_pos)
        return Task.cont

    def _tk_update(self, task):
        try:
            self.tk_root.update()
        except Exception:
            pass
        return Task.cont

    # ---------------2. Graphik & UI (GUI-/Tk-/Matplotlib-Funktionen)---------------
    def open_graph(self):
        # Starte den Graphprozess per Taste G (nur, wenn er noch nicht läuft)
        if self.graph_process is None or not self.graph_process.is_alive():
            from multiprocessing import Queue, Process
            self.graph_queue = Queue()

            # Sende alle bisher gesammelten Daten in die Queue:
            for data in self.graph_data:
                try:
                    self.graph_queue.put(data, block=False)
                except Exception:
                    pass

            from graph_pyqt import graph_process_pyqt
            self.graph_process = Process(target=graph_process_pyqt, args=(self.graph_queue,))
            self.graph_process.start()
            print("Graphprozess gestartet.")
        else:
            print("Graphprozess läuft bereits.")

    def init_graph(self):
        plt.ion()
        self.fig, (self.ax1, self.ax2, self.ax3) = plt.subplots(3, 1, figsize=(8, 9))

        # Erster Plot: Pakete pro Minute
        self.line1, = self.ax1.plot([], [], marker="o", label="Pakete pro Minute")
        self.ax1.set_xlabel("Simulationszeit (s)")
        self.ax1.set_ylabel("Pakete pro Minute")
        self.ax1.set_title("Abgegebene Pakete pro Minute")
        self.ax1.legend()
        self.ax1.grid(True)

        # Zweiter Plot: Durchschnittliche Liegedauer
        self.line2, = self.ax2.plot([], [], marker="o", color="orange", label="Durchschnittliche Liegedauer (s)")
        self.ax2.set_xlabel("Simulationszeit (s)")
        self.ax2.set_ylabel("Liegedauer (s)")
        self.ax2.set_title("Durchschnittliche Liegedauer")
        self.ax2.legend()
        self.ax2.grid(True)

        # Dritter Plot: Durchschnittliche Lieferzeit
        self.line3, = self.ax3.plot([], [], marker="o", color="green", label="Durchschnittliche Lieferzeit (s)")
        self.ax3.set_xlabel("Simulationszeit (s)")
        self.ax3.set_ylabel("Lieferzeit (s)")
        self.ax3.set_title("Durchschnittliche Lieferzeit")
        self.ax3.legend()
        self.ax3.grid(True)

        plt.show(block=False)
        # Starte im Tkinter-Hauptloop eine periodische Aktualisierung:
        self.tk_root.after(500, self.tk_graph_update)  # alle 500ms

    def tk_graph_update(self):
        # GIL sichern: Gibt einen Statuswert zurück, der später wieder freigegeben wird.
        gil_state = ctypes.pythonapi.PyGILState_Ensure()
        try:
            times = [data[0] for data in self.graph_data]
            rates = [data[1] for data in self.graph_data]
            dwell = [data[2] for data in self.graph_data]
            delivery = [data[3] for data in self.graph_data]

            self.line1.set_data(times, rates)
            self.ax1.relim()
            self.ax1.autoscale_view()

            self.line2.set_data(times, dwell)
            self.ax2.relim()
            self.ax2.autoscale_view()

            self.line3.set_data(times, delivery)
            self.ax3.relim()
            self.ax3.autoscale_view()

            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()
        finally:
            ctypes.pythonapi.PyGILState_Release(gil_state)

        # Nächsten Aufruf in 500ms einplanen
        self.tk_root.after(500, self.tk_graph_update)

    def update_graph_task(self, task):
        times = [data[0] for data in self.graph_data]
        rates = [data[1] for data in self.graph_data]
        dwell = [data[2] for data in self.graph_data]
        delivery = [data[3] for data in self.graph_data]

        self.line1.set_data(times, rates)
        self.ax1.relim()
        self.ax1.autoscale_view()

        self.line2.set_data(times, dwell)
        self.ax2.relim()
        self.ax2.autoscale_view()

        self.line3.set_data(times, delivery)
        self.ax3.relim()
        self.ax3.autoscale_view()

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(0.001)
        return Task.cont

    def update_info_display(self, task):
        tot = self.sim_clock
        h = int(tot // 3600)
        m = int((tot % 3600) // 60)
        s = tot % 60
        formatted = f"{h}h {m}m {s:.1f}s"

        # Bestimme die maximale Liegedauer aktueller Pakete an den Annahmestationen
        current_max = 0.0
        for station, (package, spawn_time, timer_np) in self.pickup_packages.items():
            elapsed = self.sim_clock - spawn_time
            if elapsed > current_max:
                current_max = elapsed
        self.max_overall_wait_time = max(self.max_overall_wait_time, current_max)
        avg_dwell = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0.0
        ppm = self.delivered_packages / (self.sim_clock / 60) if self.sim_clock > 0 else 0

        # Lieferzeit-Kennzahlen ermitteln: für Fahrzeuge, die aktuell ein Paket tragen
        current_delivery_time = 0.0
        for veh in self.garage_vehicles:
            if veh.getPythonTag("package_attached"):
                ds = veh.getPythonTag("delivery_start_time")
                if ds:
                    elapsed_delivery = self.sim_clock - ds
                    current_delivery_time = max(current_delivery_time, elapsed_delivery)
        avg_delivery_time = self.total_delivery_time / self.total_delivery_count if self.total_delivery_count > 0 else 0.0

        # Aktualisiere den Info-Label-Text
        self.info_label['text'] = (
            f"Laufzeit: {formatted}\n"
            f"Abgegebene Pakete: {self.delivered_packages}\n"
            f"Pakete pro Minute: {ppm:.1f}\n"
            f"Liegedauer (aktuell): {current_max:.1f}s\n"
            f"Liegedauer (maximal): {self.max_overall_wait_time:.1f}s\n"
            f"Durchschn. Liegedauer: {avg_dwell:.1f}s\n"
            f"Lieferzeit (aktuell): {current_delivery_time:.1f}s\n"
            f"Lieferzeit (maximal): {self.max_overall_delivery_time:.1f}s\n"
            f"Durchschn. Lieferzeit: {avg_delivery_time:.1f}s"
        )
        return Task.cont

    def update_graph_task(self, task):
        times = [data[0] for data in self.graph_data]
        rates = [data[1] for data in self.graph_data]
        dwell = [data[2] for data in self.graph_data]
        delivery = [data[3] for data in self.graph_data]

        self.line1.set_data(times, rates)
        self.ax1.relim()
        self.ax1.autoscale_view()

        self.line2.set_data(times, dwell)
        self.ax2.relim()
        self.ax2.autoscale_view()

        self.line3.set_data(times, delivery)
        self.ax3.relim()
        self.ax3.autoscale_view()

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        plt.pause(0.001)
        return Task.cont

    def on_graph_close(self, event):
        self.graph_opened = False
        self.taskMgr.remove("UpdateGraphTask")

    def update_graph_data(self, task):
        if self.sim_clock > 0:
            ppm = self.delivered_packages / (self.sim_clock / 60)
        else:
            ppm = 0.0
        avg_dwell = self.total_dwell_time / self.picked_up_count if self.picked_up_count > 0 else 0.0
        avg_delivery = self.total_delivery_time / self.total_delivery_count if self.total_delivery_count > 0 else 0.0

        new_data = (self.sim_clock, ppm, avg_dwell, avg_delivery)
        # Speichere alle Daten ab Simulationsbeginn:
        self.graph_data.append(new_data)

        # Zusätzlich: Falls der Graphprozess aktiv ist, schicke den neuen Datensatz auch an die Queue
        if self.graph_queue is not None:
            try:
                self.graph_queue.put(new_data, block=False)
            except Exception:
                pass
        return Task.cont

    def show_order_list(self):
        if self.order_win is None:
            self.order_win = tk.Tk()
            self.order_win.title("Auftragsübersicht")
            self.order_win.protocol("WM_DELETE_WINDOW", self.close_order_window)
            # Hier werden nur die gewünschten Spalten "ID", "Annahmestation", "Ziel" und "Fahrzeug" definiert.
            self.order_tree = ttk.Treeview(
                self.order_win,
                columns=("ID", "Annahmestation", "Ziel", "Fahrzeug"),
                show="headings",
                height=15
            )
            self.order_tree.heading("ID", text="Auftrags ID")
            self.order_tree.heading("Annahmestation", text="Annahmestation")
            self.order_tree.heading("Ziel", text="Ziel")
            self.order_tree.heading("Fahrzeug", text="Fahrzeug")
            self.order_tree.column("ID", width=100, anchor="center")
            self.order_tree.column("Annahmestation", width=150, anchor="center")
            self.order_tree.column("Ziel", width=150, anchor="center")
            self.order_tree.column("Fahrzeug", width=100, anchor="center")
            self.order_tree.pack(fill=tk.BOTH, expand=True)
        else:
            self.order_win.deiconify()
        self.update_order_table()
        self.order_win.lift()

    def close_order_window(self):
        if self.order_win is not None:
            self.order_win.withdraw()

    #-------Fahrzeugsteuerung(Bedienfenster)-------
    def update_vehicle_control(self):
        for veh, var in self.vehicle_state_vars.items():
            new_state = var.get()
            if new_state == "idle" and veh.getPythonTag("current_order") is not None:
                veh.setPythonTag("standby_pending", True)
                print(f"Fahrzeug {veh.getPythonTag('vehicle_id')}: Standby angefordert (Auftrag wird fortgesetzt).")
            else:
                veh.setPythonTag("standby_pending", False)
                veh.setPythonTag("order_state", new_state)
                print(f"Fahrzeug {veh.getPythonTag('vehicle_id')}: Zustand auf {new_state} gesetzt.")

    def _tk_update(self, task):
        try:
            self.tk_root.update()
        except Exception:
            pass
        return Task.cont

    def update_cable(self, task):
        # Verwende die simulative Zeit, die bereits in update_sim_clock hochgezählt wird
        t = self.sim_clock
        new_height = 0.5 + 0.5 * math.sin(t * 2.0)
        self.fork_node.setZ(new_height)
        return Task.cont

    def create_garage_vehicles(self):
        self.garage_vehicles = []
        vehicle_id_counter = 1
        for park in self.garagen_parking_points:
            veh = self.create_vehicle(park_point=park)
            veh.setH(veh.getH() + 180)
            intersection = Vec3(0.5, 0.05, 1.0)
            newPos = park - veh.getQuat().xform(intersection)
            newPos.setZ(0)
            veh.setPos(newPos)

            # Fahrzeuge starten im Standby (idle)
            veh.setPythonTag("current_order", None)
            veh.setPythonTag("order_state", "idle")
            veh.setPythonTag("package_attached", False)
            veh.setPythonTag("vehicle_id", vehicle_id_counter)
            # Speichere den Parkpunkt als Rückkehrziel
            veh.setPythonTag("garage_target", park)
            # Speichere auch das Anfangs-Heading, um es später beim Parken wiederherzustellen.
            veh.setPythonTag("start_heading", veh.getH())
            vehicle_id_counter += 1

            self.garage_vehicles.append(veh)

            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.2)
            marker.setColor(LColor(0, 0, 1, 1))
            marker.setPos(park.getX(), park.getY(), 0)
            marker.reparentTo(self.render)

            # Füge einen Textknoten hinzu, der die Fahrzeugnummer vorne auf dem Fahrzeug anzeigt.
            # Wir suchen den Mast-Knoten.
            mast = veh.find("**/mast")
            if not mast.isEmpty():
                from panda3d.core import TextNode
                tn = TextNode("vehicle_number")
                tn.setText(str(veh.getPythonTag("vehicle_id")))
                tn.setTextColor(0, 0, 0, 1)  # Schwarz
                tn.setAlign(TextNode.ACenter)
                text_np = mast.attachNewNode(tn)
                # Positioniere den Text relativ zum Mast: Wir nutzen den Vektor "intersection"
                # und versetzen ihn in Z-Richtung um 0.2 Einheiten oberhalb des Zylinders.
                text_np.setPos(intersection.x, intersection.y, intersection.z + 0.2)
                text_np.setScale(0.8)
                text_np.setHpr(0, 0, 0)
            else:
                from panda3d.core import TextNode
                tn = TextNode("vehicle_number")
                tn.setText(str(veh.getPythonTag("vehicle_id")))
                tn.setTextColor(0, 0, 0, 1)
                tn.setAlign(TextNode.ACenter)
                text_np = veh.attachNewNode(tn)
                text_np.setPos(0, 1.2, 1.5)
                text_np.setScale(0.8)
                text_np.setHpr(0, 0, 0)

            self.taskMgr.add(partial(self.vehicle_order_task, veh),
                             f"VehicleOrderTask_{veh.getPythonTag('vehicle_id')}")

    # --------------- Erstellung des Fahrzeugs---------------
    def create_vehicle(self, park_point=None):
        # Erzeuge den übergeordneten Fahrzeug-Knoten
        vehicle_node = self.render.attachNewNode("vehicle")

        # --------------------------
        # Chassis erstellen (1 x 0.5 x 1.2, Farbe Rot)
        # --------------------------
        box_chassis = self.create_box(1, 0.5, 1.2, (1.0, 0.0, 0.0, 1))
        node_chassis = vehicle_node.attachNewNode(box_chassis)
        node_chassis.setTwoSided(True)
        node_chassis.setPos(0, 0, 0)
        edges_chassis = self.create_box_edges(1, 0.5, 1.2, (0, 0, 0, 1))
        edges_chassis.reparentTo(node_chassis)

        # --------------------------
        # Gabel (Fork) erstellen: Zwei Zähne
        # --------------------------
        fork_node = vehicle_node.attachNewNode("fork")
        fork_node.setPos(0, -1.2, 0)
        vehicle_node.setPythonTag("fork_node", fork_node)

        left_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_left = fork_node.attachNewNode(left_tooth)
        node_left.setTwoSided(True)
        right_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_right = fork_node.attachNewNode(right_tooth)
        node_right.setTwoSided(True)
        node_right.setPos(0.8, 0, 0)

        # --------------------------
        # Statt weißer Kante von der Gabel: bereits eingezeichnete grüne Mittellinie verwenden.
        # In diesem Beispiel nehmen wir an, dass du schon eine „mittlere“ Linie gezeichnet hast.
        # Zeichne die grüne Mittellinie, z. B. von einem Punkt an der Gabel (als Ausgangspunkt)
        # bis zu einem Referenzpunkt – hier nutzen wir einen zuvor festgelegten Offset.
        #
        # Wir definieren:
        #   - Den Ausgangspunkt als den grün markierten Punkt, der den mittleren Punkt der Gabel repräsentieren soll.
        #   - Den Zielpunkt als den Referenzpunkt, der als Idealwert in create_vehicle bestimmt wurde.
        # In unserem Beispiel berechnen wir den Zielpunkt einmalig aus den lokalen Offsets an der weißen Kante.
        # (Diese Werte kannst du bei Bedarf anpassen.)
        left_corner_local = Vec3(0, 0, 0.05)
        right_corner_local = Vec3(1.0, 0, 0.05)
        left_global = fork_node.getPos(self.render) + left_corner_local
        right_global = fork_node.getPos(self.render) + right_corner_local
        # Berechne den idealen (statischen) Mittelpunkt als Referenz – dieser wird nur einmal gesetzt.
        midpoint_white = (left_global + right_global) * 0.5
        # Nun lege den grünen Marker so, dass er exakt in der Mitte der Gabel liegt.
        # Hier entspricht der grüne Punkt der Mittellinie der Gabel.
        green_point_global = midpoint_white  # Hier wird angenommen, dass der ideale Mittelpunkt gleich dem Referenzpunkt ist.
        green_marker = self.create_box(0.05, 0.05, 0.05, (0, 1, 0, 1))
        green_marker_np = vehicle_node.attachNewNode(green_marker)
        green_marker_np.setPos(green_point_global - Vec3(0.025, 0.025, 0.025))
        vehicle_node.setPythonTag("fork_green", green_marker_np)

        # Zeichne die grüne Mittellinie.
        # Als Beispiel: Zeichne eine Linie vom grünen Marker in Richtung +Y (relativ zum Fahrzeug),
        # weil du den idealen Zustand so festgelegt hast, dass genau diese Linie mit der Station übereinstimmen soll.
        ls_mid = LineSegs()
        ls_mid.setThickness(2.0)
        ls_mid.setColor(0, 1, 0, 1)  # grün
        # Starte die Linie am grünen Marker.
        ls_mid.moveTo(green_point_global)
        # Zeichne beispielsweise eine Linie 1 Einheit lang in +Y-Richtung:
        ls_mid.drawTo(green_point_global + Vec3(0, 1, 0))
        fork_center_line = vehicle_node.attachNewNode(ls_mid.create())
        # Speichere den NodePath der grünen Mittellinie
        vehicle_node.setPythonTag("fork_center_line", fork_center_line)
        print("[DEBUG] create_vehicle: Grüne Mittellinie (fork_center_line) gesetzt.")

        # --------------------------
        # Restliche Fahrzeugteile (Mast, Lenkachse, etc.)
        # --------------------------
        mast_node = vehicle_node.attachNewNode("mast")
        mast_node.setPos(0, 0.2, 1.2)
        top_bar = self.create_box(1, 0.1, 0.1, (0.2, 0.2, 0.2, 1))
        top_bar_node = mast_node.attachNewNode(top_bar)
        top_bar_node.setPos(0, 0, 0.9)
        bottom_bar = self.create_box(1, 0.1, 0.1, (0.2, 0.2, 0.2, 1))
        bottom_bar_node = mast_node.attachNewNode(bottom_bar)
        bottom_bar_node.setPos(0, 0, 0)
        left_bar = self.create_box(0.1, 0.1, 0.8, (0.2, 0.2, 0.2, 1))
        left_bar_node = mast_node.attachNewNode(left_bar)
        left_bar_node.setPos(0, 0, 0.1)
        right_bar = self.create_box(0.1, 0.1, 0.8, (0.2, 0.2, 0.2, 1))
        right_bar_node = mast_node.attachNewNode(right_bar)
        right_bar_node.setPos(0.9, 0, 0.1)
        mast_node.setTwoSided(True)
        mast_node.setPos(0, 0.2, 1.2)
        self.add_diagonals_to_mast(mast_node)

        intersection = Vec3(0.5, 0.05, 1.0)
        cylinder_node = NodePath(self.create_cylinder(0.1, 0.1, 16, (1, 1, 0, 1)))
        cylinder_node.reparentTo(mast_node)
        cylinder_node.setPos(intersection)

        # --------------------------
        # Lenkachse erzeugen (Pivot-Node)
        # --------------------------
        steering_axis = mast_node.attachNewNode("steering_axis")
        steering_axis.setPos(0.5, 0.25, -1.2)
        steering_axis.setH(90)
        vehicle_node.setPythonTag("steering_axis", steering_axis)

        cylinder_node = NodePath(self.create_cylinder(0.1, 0.1, 16, (1, 1, 0, 1)))
        cylinder_node.reparentTo(steering_axis)
        cylinder_node.setPos(0, 0, 0)
        self.vehicle_cylinder = steering_axis
        self.add_steering_arrow(steering_axis, color=(0, 1, 0, 1))

        # --------------------------
        # Positioniere das Fahrzeug am Parkpunkt
        # --------------------------
        if park_point is None:
            vehicle_node.setPos(0, 0, 0)
        else:
            intersection = Vec3(0, 0, 1.0)
            vehicle_node.setPos(park_point - vehicle_node.getQuat().xform(intersection))

        # ********** Ursprung (Koordinatensystem) am Fahrzeug einzeichnen **********
        ls_x = LineSegs()
        ls_x.setThickness(2)
        ls_x.setColor(LColor(1, 0, 0, 1))
        ls_x.moveTo(0, 0, 0)
        ls_x.drawTo(1, 0, 0)
        vehicle_node.attachNewNode(ls_x.create())

        ls_y = LineSegs()
        ls_y.setThickness(2)
        ls_y.setColor(LColor(0, 1, 0, 1))
        ls_y.moveTo(0, 0, 0)
        ls_y.drawTo(0, 1, 0)
        vehicle_node.attachNewNode(ls_y.create())

        ls_z = LineSegs()
        ls_z.setThickness(2)
        ls_z.setColor(LColor(0, 0, 1, 1))
        ls_z.moveTo(0, 0, 0)
        ls_z.drawTo(0, 0, 1)
        vehicle_node.attachNewNode(ls_z.create())

        from panda3d.core import TextNode
        tn_x = TextNode("label_x")
        tn_x.setText("X")
        tn_x.setTextColor(1, 0, 0, 1)
        label_x = vehicle_node.attachNewNode(tn_x)
        label_x.setScale(0.3)
        label_x.setPos(2.0, 0, 0)

        tn_y = TextNode("label_y")
        tn_y.setText("Y")
        tn_y.setTextColor(0, 1, 0, 1)
        label_y = vehicle_node.attachNewNode(tn_y)
        label_y.setScale(0.3)
        label_y.setPos(0, 2.0, 0)

        tn_z = TextNode("label_z")
        tn_z.setText("Z")
        tn_z.setTextColor(0, 0, 1, 1)
        label_z = vehicle_node.attachNewNode(tn_z)
        label_z.setScale(0.3)
        label_z.setPos(0, 0, 2.0)

        return vehicle_node

    def add_steering_arrow(self, steering_axis, color=(0, 1, 0, 1)):
        """
        Erzeugt einen Pfeil, der die Vorwärtsrichtung (lokale X-Achse) des Lenkpivots anzeigt.
        Der Pfeil wird als Kind des übergebenen steering_axis-Node angehängt und passt sich
        automatisch dessen Rotation an.
        """
        arrow_ls = LineSegs()
        arrow_ls.setThickness(2.0)
        arrow_ls.setColor(*color)

        # Zeichne eine Linie von (0,0,0) bis (2,0,0) – das ist die Basis des Pfeils
        arrow_ls.moveTo(0, 0, 0)
        arrow_ls.drawTo(2, 0, 0)

        # Zeichne den Pfeilkopf: zwei kurze schräge Linien am Ende der Pfeillinie
        arrow_ls.moveTo(2, 0, 0)
        arrow_ls.drawTo(1.5, 0.3, 0)
        arrow_ls.moveTo(2, 0, 0)
        arrow_ls.drawTo(1.5, -0.3, 0)

        arrow_np = steering_axis.attachNewNode(arrow_ls.create())
        arrow_np.setPos(0, 0, 0)  # Falls nötig, hier noch zusätzlichen Offset anpassen
        return arrow_np

    def rotate_around_pivot(self, vehicle, pivot, delta_angle):
        """
        Dreht das Fahrzeug (vehicle) um den gegebenen Pivotpunkt (pivot) um delta_angle (in Grad).
        Dabei wird die Position des Fahrzeugs neu berechnet, sodass es um den Pivot rotiert.
        """
        # Aktuelle globale Fahrzeugposition
        pos = vehicle.getPos(self.render)
        # Globaler Pivotpunkt
        pivot_pos = pivot.getPos(self.render)
        # Berechne den Vektor vom Pivot zum Fahrzeug
        rel = pos - pivot_pos
        # Wandle den Drehwinkel in Bogenmaß um
        rad = math.radians(delta_angle)
        cos_val = math.cos(rad)
        sin_val = math.sin(rad)
        # Drehe den relativen Vektor
        new_x = rel.getX() * cos_val - rel.getY() * sin_val
        new_y = rel.getX() * sin_val + rel.getY() * cos_val
        new_rel = Vec3(new_x, new_y, rel.getZ())
        # Neue globale Fahrzeugposition
        new_pos = pivot_pos + new_rel
        vehicle.setPos(new_pos)
        # Aktualisiere auch das Heading des Fahrzeugs (aufaddieren des Drehwinkels)
        vehicle.setH(vehicle.getH() + delta_angle)

    def add_diagonals_to_mast(self, mast_node):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(1.0, 0.5, 0.0, 1)
        ls.moveTo(0, 0, 1.0)
        ls.drawTo(1, 0.1, 1.0)
        ls.moveTo(1, 0, 1.0)
        ls.drawTo(0, 0.1, 1.0)
        mast_node.attachNewNode(ls.create())

    def create_cylinder(self, diameter, height, segments, color):
        fmt = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData("cylinder", fmt, Geom.UHStatic)
        vwriter = GeomVertexWriter(vdata, "vertex")
        nwriter = GeomVertexWriter(vdata, "normal")
        cwriter = GeomVertexWriter(vdata, "color")
        r = diameter / 2.0
        top_z = height / 2.0
        bottom_z = -height / 2.0

        vwriter.addData3f(0, 0, top_z)
        nwriter.addData3f(0, 0, 1)
        cwriter.addData4f(*color)

        for i in range(segments):
            angle = 2 * math.pi * i / segments
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            vwriter.addData3f(x, y, top_z)
            nwriter.addData3f(0, 0, 1)
            cwriter.addData4f(*color)

        vwriter.addData3f(0, 0, bottom_z)
        nwriter.addData3f(0, 0, -1)
        cwriter.addData4f(*color)

        for i in range(segments):
            angle = 2 * math.pi * i / segments
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            vwriter.addData3f(x, y, bottom_z)
            nwriter.addData3f(0, 0, -1)
            cwriter.addData4f(*color)

        top_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(1, segments + 1):
            next_i = 1 if i == segments else i + 1
            top_triangles.addVertices(0, i, next_i)
            top_triangles.closePrimitive()

        bottom_center = segments + 1
        bottom_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(segments):
            curr = segments + 2 + i
            next_i = segments + 2 if i == segments - 1 else curr + 1
            bottom_triangles.addVertices(bottom_center, next_i, curr)
            bottom_triangles.closePrimitive()

        side_triangles = GeomTriangles(Geom.UHStatic)
        for i in range(1, segments + 1):
            next_i = 1 if i == segments else i + 1
            top_i = i
            bottom_i = segments + 1 + i
            bottom_next = segments + 1 + next_i
            side_triangles.addVertices(top_i, next_i, bottom_next)
            side_triangles.closePrimitive()
            side_triangles.addVertices(top_i, bottom_next, bottom_i)
            side_triangles.closePrimitive()

        geom = Geom(vdata)
        geom.addPrimitive(top_triangles)
        geom.addPrimitive(bottom_triangles)
        geom.addPrimitive(side_triangles)
        node = GeomNode("cylinder")
        node.addGeom(geom)
        return node


    def create_box(self, width, depth, height, color):
        fmt = GeomVertexFormat.getV3n3cp()
        vdata = GeomVertexData("box", fmt, Geom.UHStatic)
        vertex = GeomVertexWriter(vdata, "vertex")
        normal = GeomVertexWriter(vdata, "normal")
        col = GeomVertexWriter(vdata, "color")

        for v in [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, -1)
            col.addData4f(*color)
        for v in [(0, 0, height), (width, 0, height), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, 1)
            col.addData4f(*color)
        for v in [(0, 0, 0), (width, 0, 0), (width, 0, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, -1, 0)
            col.addData4f(*color)
        for v in [(0, depth, 0), (width, depth, 0), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 1, 0)
            col.addData4f(*color)
        for v in [(0, 0, 0), (0, depth, 0), (0, depth, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(-1, 0, 0)
            col.addData4f(*color)
        for v in [(width, 0, 0), (width, depth, 0), (width, depth, height), (width, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(1, 0, 0)
            col.addData4f(*color)

        tris = GeomTriangles(Geom.UHStatic)
        for i in range(6):
            base = i * 4
            tris.addVertices(base, base + 1, base + 2)
            tris.closePrimitive()
            tris.addVertices(base, base + 2, base + 3)
            tris.closePrimitive()

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode("box")
        node.addGeom(geom)
        return node

    def create_box_edges(self, width, depth, height, color):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(*color)
        ls.moveTo(0, 0, 0)
        ls.drawTo(width, 0, 0)
        ls.drawTo(width, depth, 0)
        ls.drawTo(0, depth, 0)
        ls.drawTo(0, 0, 0)
        ls.moveTo(0, 0, height)
        ls.drawTo(width, 0, height)
        ls.drawTo(width, depth, height)
        ls.drawTo(0, depth, height)
        ls.drawTo(0, 0, height)
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, height)
        ls.moveTo(width, 0, 0)
        ls.drawTo(width, 0, height)
        ls.moveTo(width, depth, 0)
        ls.drawTo(width, depth, height)
        ls.moveTo(0, depth, 0)
        ls.drawTo(0, depth, height)
        return NodePath(ls.create())

    # ---------------6. Paket- & Auftragsverwaltung---------------
        # Beispiel einer Methode, die weiterhin auf die extrahierten Umgebungselemente zugreift:
    def spawn_package_at_station(self, station):
        pos = station.getPos(self.render)
        package = self.erzeuge_wuerfel(pos.x, pos.y, pos.z, LColor(1, 1, 0, 1))
        spawn_time = self.sim_clock
        timer_text = TextNode("package_timer")
        timer_text.setText("0.0s")
        timer_np = package.attachNewNode(timer_text)
        timer_np.setScale(0.5)
        timer_np.setPos(0, 0, 1.2)

        # Paket eintragen
        self.pickup_packages[station] = (package, spawn_time, timer_np)
        self.last_removed[station] = self.sim_clock

        # Je nach gewählter Verteilung kannst du hier Anpassungen vornehmen.
        # Für den Moment wählen wir einfach zufällig aus allen Abgabestationen,
        # falls keine spezielle Logik für die Verteilung implementiert ist.
        target_index = random.randint(1, len(self.abgabe_stations))

        order = {
            "id": self.next_order_id,
            "status": "Wartend",
            "ziel": f"Abgabestation {target_index}",
            "annahmestation": station.getName(),
            "pickup_station": station,
            "package": package,
            "timer_np": timer_np,
            "spawn_time": spawn_time
        }
        self.orders[order["id"]] = order
        self.orders_queue.append(order)
        self.next_order_id += 1

        print(f"Neuer Auftrag erstellt: {order}")

    def erzeuge_wuerfel(self, x, y, z, color):
        wuerfel = self.loader.loadModel("models/box")
        wuerfel.setScale(1, 1, 1)
        # Hier wird der Höhenoffset innerhalb der Methode gesetzt:
        wuerfel.setPos(x, y, z + 1)
        wuerfel.setColor(color)
        wuerfel.reparentTo(self.render)
        return wuerfel

    def update_package_timers(self, task):
        for station, (package, spawn_time, timer_np) in list(self.pickup_packages.items()):
            # Prüfe, ob der Timer-Knoten noch gültig ist
            if not timer_np.isEmpty():
                elapsed = self.sim_clock - spawn_time
                timer_np.node().setText(f"{elapsed:.1f}s")
            else:
                del self.pickup_packages[station]
        return Task.cont

    def check_and_spawn_packages(self, task):
        # Verwende den neuen Delay-Wert aus den Einstellungen
        spawn_delay = self.package_spawn_delay
        for station in self.annahme_stations:
            if station not in self.pickup_packages:
                last_time = self.last_removed.get(station, self.sim_clock)
                if (self.sim_clock - last_time) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

        # Beispiel für eine vorhandene Methode, die auf die Umgebungselemente zugreift:
    def update_order_table(self):
        # Lösche alle vorhandenen Einträge in der Auftragsliste.
        for entry in self.order_tree.get_children():
            self.order_tree.delete(entry)

        # Iteriere über alle Aufträge.
        for order_id, order in list(self.orders.items()):
            # Extrahiere aus dem Annahmestationsnamen die Stationsnummer (oder verwende "N/A").
            pickup_station_str = order.get("annahmestation", "N/A")
            if pickup_station_str != "N/A" and "_" in pickup_station_str:
                pickup_number = pickup_station_str.split("_")[-1]
            else:
                pickup_number = "N/A"

            # Extrahiere aus dem Ziel (z.B. "Abgabestation 5") die Stationsnummer.
            target_station_str = order.get("ziel", "N/A")
            if target_station_str != "N/A" and " " in target_station_str:
                target_number = target_station_str.split()[-1]
            else:
                target_number = "N/A"

            # Zeige den zugewiesenen Fahrzeugnamen an (oder "-" falls noch keiner zugeordnet wurde).
            vehicle_display = order.get("vehicle", "-")

            self.order_tree.insert("", tk.END,
                                   values=(order_id, pickup_number, target_number, vehicle_display))
        self.order_win.update()

    def update_order_status(self, task):
        # Entferne Aufträge, die den Status "Abgegeben" haben und deren Lieferzeit älter als 2 Sekunden ist.
        for order_id, order in list(self.orders.items()):
            if order.get("status") == "Abgegeben" and self.sim_clock - order.get("delivered_at", 0) >= 2:
                del self.orders[order_id]
        if hasattr(self, 'order_win') and self.order_win is not None:
            self.update_order_table()
        return Task.cont

    def deliver_first_order(self):
        # Diese Methode wird beim Paket-Zustellen aufgerufen.
        for order_id, order in self.orders.items():
            if order.get("status") == "Wartend":
                order["status"] = "Abgegeben"
                order["delivered_at"] = self.sim_clock
                print(f"Auftrag {order['id']} wurde geliefert.")
                break

    # ---------------7. Cargo-Handling (Pickup, Drop & Timer)---------------
    def pickup_package(self, vehicle, station):
        # Falls das Fahrzeug bereits ein Paket trägt, abbrechen.
        if vehicle.getPythonTag("package_attached"):
            return

        # Führe den Pickup nur aus, wenn an der Station ein Paket vorhanden ist.
        if station in self.pickup_packages:
            # Hole das Paket, den Spawn-Zeitpunkt und den zugehörigen Timer-Knoten.
            package, spawn_time, timer_np = self.pickup_packages.pop(station)
            # Entferne den Timer-Knoten, sodass der angezeigte Zähler nicht weiter aktualisiert wird.
            timer_np.removeNode()
            # Berechne die Liegedauer (Differenz zwischen aktueller Simulationszeit und Spawn-Zeit).
            dwell_time = self.sim_clock - spawn_time
            # Aktualisiere globale Kennzahlen.
            self.total_dwell_time += dwell_time
            self.picked_up_count += 1

            # Suche in den Aufträgen nach dem Auftrag, dessen Paket mit diesem Paket übereinstimmt,
            # und speichere den errechneten Endwert (fixe Liegedauer) sowie den Status.
            for order_id, order in self.orders.items():
                if order.get("package") == package:
                    order["dwell_time"] = dwell_time
                    order["status"] = "Abgeholt"
                    break

            # Hole Referenzen zum Gabel-Knoten und zum grünen Marker des Fahrzeugs.
            fork_node = vehicle.getPythonTag("fork_node")
            fork_green = vehicle.getPythonTag("fork_green")
            green_point_pos = fork_green.getPos(fork_node)

            # Übergib das Paket an den Gabel-Knoten (sodass es optisch dem Fahrzeug zugeordnet wird)
            # und positioniere es relativ zum grünen Marker.
            package.wrtReparentTo(fork_node)
            package.setPos(green_point_pos.getX() + 0.5,
                           green_point_pos.getY() - 0.5,
                           green_point_pos.getZ() + 1)
            self.cargos[vehicle] = package

            # Starte den Lieferzeit-Timer: Speichere den Zeitpunkt, an dem das Paket abgeholt wurde,
            # und hänge einen neuen Timer-Knoten an das Paket.
            vehicle.setPythonTag("delivery_start_time", self.sim_clock)
            from panda3d.core import TextNode
            delivery_timer_text = TextNode("delivery_timer")
            delivery_timer_text.setText("0.0s")
            delivery_timer_np = package.attachNewNode(delivery_timer_text)
            delivery_timer_np.setScale(0.5)
            delivery_timer_np.setPos(0, 0, 1.2)
            package.setPythonTag("delivery_timer", delivery_timer_np)

            # Aktualisiere den Zeitpunkt, zu dem an dieser Station zuletzt ein Paket entfernt wurde.
            self.last_removed[station] = self.sim_clock
            if station in self.occupied_pickups:
                self.occupied_pickups.remove(station)

    def drop_cargo(self, vehicle):
        cargo = self.cargos.get(vehicle)
        if cargo:
            cargo.wrtReparentTo(self.render)
            # Paket wird in Fahrzeug-Nähe abgelegt (kleiner Z-Offset)
            targetPos = vehicle.getPos(self.render) + Vec3(1.2, 1, 1)
            cargo.setPos(targetPos)

            # Berechne Lieferzeit:
            delivery_start = vehicle.getPythonTag("delivery_start_time")
            if delivery_start is not None:
                delivery_time = self.sim_clock - delivery_start
                self.total_delivery_time += delivery_time
                self.total_delivery_count += 1
                self.max_overall_delivery_time = max(self.max_overall_delivery_time, delivery_time)
                vehicle.clearPythonTag("delivery_start_time")

            # Entferne den Lieferzeit-Timer vom Paket
            delivery_timer_np = cargo.getPythonTag("delivery_timer")
            if delivery_timer_np:
                delivery_timer_np.removeNode()

            self.delivered_packages += 1

            # Starte einen Task, der nach 3 Sekunden das Paket entfernt
            taskMgr.doMethodLater(3, self.removeCargoTask, "removeCargoTask", extraArgs=[cargo], appendTask=True)

    def update_delivery_timers(self, task):
        for vehicle, package in list(self.cargos.items()):
            delivery_start = vehicle.getPythonTag("delivery_start_time")
            if delivery_start:
                elapsed_delivery = self.sim_clock - delivery_start
                delivery_timer_np = package.getPythonTag("delivery_timer")
                if delivery_timer_np and not delivery_timer_np.isEmpty():
                    delivery_timer_np.node().setText(f"{elapsed_delivery:.1f}s")
        return Task.cont

    def removeCargoTask(self, cargo, task):
        cargo.removeNode()  # Entfernt das Paket aus der Szene
        return task.done


    # ---------------8. Auftrags-/Fahrzeuglogik---------------
    def select_next_order(self, vehicle):
        # Sammle alle Aufträge, die noch "Wartend" sind
        waiting_orders = [order for order in self.orders.values() if order.get("status") == "Wartend"]
        if not waiting_orders:
            return None

        # Aktualisiere die Dwell-Zeit für jeden Auftrag
        for order in waiting_orders:
            order["dwell_time"] = self.sim_clock - order.get("spawn_time", self.sim_clock)

        # Wähle den Auftrag mit der maximalen Dwell-Zeit (evtl. mit etwas Toleranz)
        max_dwell = max(order["dwell_time"] for order in waiting_orders)
        tolerance = 0.01
        candidates = [order for order in waiting_orders if abs(order["dwell_time"] - max_dwell) < tolerance]
        if not candidates:
            candidates = waiting_orders

        # Finde aus den Kandidaten den Auftrag, dessen Pickup-Station (order["pickup_station"])
        # am nächsten zur aktuellen Fahrzeugposition liegt.
        vehicle_pos = vehicle.getPos(self.render)
        candidates.sort(key=lambda order: (order["pickup_station"].getPos(self.render) - vehicle_pos).length())
        return candidates[0]

    def show_vehicle_control(self):
        # Falls das Fenster bereits existiert, wiederverwenden
        if hasattr(self, "control_win") and self.control_win.winfo_exists():
            self.control_win.deiconify()
            self.control_win.lift()
            self.control_win.focus_force()
            return

        self.control_win = tk.Toplevel(self.tk_root)
        self.control_win.title("Kontrollfenster")
        self.control_win.protocol("WM_DELETE_WINDOW", self.control_win.withdraw)
        self.control_win.attributes("-topmost", True)
        self.control_win.after(100, lambda: self.control_win.attributes("-topmost", False))

        # ---------------- Fahrzeugsteuerung ----------------
        # Zunächst einen Button einfügen, der ALLE Fahrzeuge auf "Aufträge bearbeiten" setzt.
        all_vehicles_btn = tk.Button(
            self.control_win,
            text="Alle Fahrzeuge auf 'Aufträge bearbeiten' setzen",
            command=lambda: [self.vehicle_state_vars[veh].set("translate") for veh in self.garage_vehicles]
        )
        all_vehicles_btn.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        # Nun die einzelnen Fahrzeugzeilen – starte ab Zeile 1
        self.vehicle_state_vars = {}
        row = 1
        for veh in self.garage_vehicles:
            frame = tk.Frame(self.control_win)
            frame.grid(row=row, column=0, sticky="w", padx=5, pady=2)
            vid = veh.getPythonTag("vehicle_id")
            label = tk.Label(frame, text=f"Fahrzeug {vid}")
            label.pack(side=tk.LEFT)
            state = veh.getPythonTag("order_state") or "idle"
            var = tk.StringVar(value=state)
            self.vehicle_state_vars[veh] = var
            rb_active = tk.Radiobutton(frame, text="Aufträge bearbeiten", variable=var, value="translate")
            rb_active.pack(side=tk.LEFT)
            rb_standby = tk.Radiobutton(frame, text="Standby", variable=var, value="idle")
            rb_standby.pack(side=tk.LEFT)
            row += 1

        update_btn = tk.Button(self.control_win, text="Übernehmen", command=self.update_vehicle_control)
        update_btn.grid(row=row, column=0, pady=5)
        row += 1

        # ---------------- Spawn-Einstellungen ----------------
        spawn_frame = tk.LabelFrame(self.control_win, text="Spawn Einstellungen", padx=5, pady=5)
        spawn_frame.grid(row=row, column=0, sticky="w", padx=5, pady=5)

        # Eingabe der Spawnverzögerung
        tk.Label(spawn_frame, text="Spawnverzögerung (Sekunden):").grid(row=0, column=0, sticky="w")
        self.spawn_delay_var = tk.DoubleVar(value=self.package_spawn_delay)
        delay_entry = tk.Entry(spawn_frame, textvariable=self.spawn_delay_var, width=6)
        delay_entry.grid(row=0, column=1, sticky="w")

        # Direkt in diesem Spawn-Feld: Button, der alle Annahmestationen auswählt
        btn_select_all_stations = tk.Button(
            spawn_frame,
            text="Alle Annahmestationen auswählen",
            command=lambda: [self.spawn_station_vars[i].set(True) for i in self.spawn_station_vars]
        )
        btn_select_all_stations.grid(row=0, column=2, padx=5)

        # Auswahl der Annahmestationen (Checkbuttons)
        tk.Label(spawn_frame, text="Annahmestationen:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        stations_frame = tk.Frame(spawn_frame)
        stations_frame.grid(row=2, column=0, columnspan=3, sticky="w")
        for i in range(min(10, len(self.annahme_stations))):
            cb = tk.Checkbutton(stations_frame, text=f"Annahmestation {i + 1}",
                                variable=self.spawn_station_vars[i])
            cb.pack(anchor="w")

        def apply_spawn_from_control():
            self.package_spawn_delay = self.spawn_delay_var.get()
            selected = []
            for i, var in self.spawn_station_vars.items():
                if var.get():
                    selected.append(self.annahme_stations[i])
            self.package_spawn_stations = selected
            print(
                f"Spawn Einstellungen übernommen: Delay={self.package_spawn_delay}s, "
                f"Stations: {[i + 1 for i, var in self.spawn_station_vars.items() if var.get()]}"
            )
            # Spawne nur an Stationen, an denen noch kein Paket existiert:
            for station in self.package_spawn_stations:
                if station not in self.pickup_packages:
                    self.spawn_package_at_station(station)
            # Option: spawn_win schließen oder offen lassen
            # self.control_win.withdraw()

        apply_btn = tk.Button(
            spawn_frame,
            text="Einstellungen übernehmen und spawnen",
            command=apply_spawn_from_control
        )
        apply_btn.grid(row=3, column=0, columnspan=3, pady=5)

    def show_spawn_control(self):
        spawn_win = tk.Toplevel(self.tk_root)
        spawn_win.title("Paketspawn Einstellungen")

        # Eingabefeld für Spawnverzögerung
        tk.Label(spawn_win, text="Spawnverzögerung (Sekunden):").pack(pady=2)
        delay_entry = tk.Entry(spawn_win)
        delay_entry.insert(0, str(self.package_spawn_delay))
        delay_entry.pack(pady=2)

        # (Dropdown für Spawn-Verteilung wurde entfernt)

        # Checkbuttons für die Auswahl der Annahmestationen
        tk.Label(spawn_win, text="Annahmestationen auswählen (1-10):").pack(pady=2)
        stations_frame = tk.Frame(spawn_win)
        stations_frame.pack(pady=2)

        station_vars = {}
        for idx, station in enumerate(self.annahme_stations):
            var = tk.BooleanVar(value=False)
            station_label = f"Annahmestation {idx + 1}"
            cb = tk.Checkbutton(stations_frame, text=station_label, variable=var)
            cb.pack(anchor="w")
            station_vars[idx] = var

        def apply_spawn_settings():
            try:
                new_delay = float(delay_entry.get())
            except ValueError:
                new_delay = self.package_spawn_delay
            new_stations = []
            for idx, var in station_vars.items():
                if var.get():
                    new_stations.append(self.annahme_stations[idx])

            self.package_spawn_delay = new_delay
            self.package_spawn_stations = new_stations

            print(f"Spawn-Einstellungen aktualisiert: Delay={new_delay}s, "
                  f"Stationen: {[f'Annahmestation {idx + 1}' for idx, var in station_vars.items() if var.get()]}")
            # Spawne nur dort Pakete, wo noch kein Paket vorhanden ist:
            for station in self.package_spawn_stations:
                if station not in self.pickup_packages:
                    self.spawn_package_at_station(station)

            spawn_win.destroy()

        tk.Button(spawn_win, text="Einstellungen speichern", command=apply_spawn_settings).pack(pady=5)

    def vehicle_order_task(self, vehicle, task):
        # Berechne dt (berücksichtigt die Simulationsgeschwindigkeit)
        dt = ClockObject.getGlobalClock().getDt() * self.speed_factor

        # (Optional) Überprüfe, ob ein Zustand gesetzt ist. Bleibt das Fahrzeug in "idle", wird nichts gemacht.
        state = vehicle.getPythonTag("order_state")
        if state is None:
            vehicle.setPythonTag("order_state", "idle")
            return Task.cont
        if state == "idle":
            return Task.cont

        # --- Modellinferenz & Trainingsdatenerfassung ---
        frame_count = vehicle.getPythonTag("frame_count")
        if frame_count is None:
            frame_count = 0
        frame_count += 1
        vehicle.setPythonTag("frame_count", frame_count)

        sensor_data = self.collect_sensor_data(vehicle)
        import numpy as np
        if self.tf_model is not None and (frame_count % 10 == 0):
            input_data = sensor_data.reshape(1, sensor_data.shape[0], sensor_data.shape[1], 1)
            prediction = self.tf_model.predict(input_data)
            model_delta_angle = prediction[0][0]
            print(f"[TF] Modell-Korrektur: {model_delta_angle:.2f}°")
        else:
            model_delta_angle = 0.0
            if self.tf_model is not None:
                print(f"[TF] Modell-Korrektur übersprungen (Frame Count: {frame_count})")
            else:
                print("[TF] Kein Modell vorhanden, Modell-Korrektur wird übersprungen.")

        ideal_correction = self.compute_ideal_steering_correction(vehicle)
        print(f"[IDEAL] Ideal berechneter Korrekturwinkel: {ideal_correction:.2f}°")
        if state == "translate":
            self.log_training_sample(sensor_data, ideal_correction)
        # --- Ende Modellinferenz & Logging ---

        # Zustandsbasierte Handler-Aufrufe:
        if state == "translate":
            self.handle_translate_phase(vehicle, dt)
        elif state == "rotate":
            self.handle_rotate_phase(vehicle, dt)
        elif state == "approach":
            self.handle_approach_phase(vehicle, dt)
        elif state == "pickup":
            self.handle_pickup_phase(vehicle, dt)
        elif state == "drive_out":
            self.handle_drive_out_phase(vehicle, dt)
        elif state == "to_delivery":
            self.handle_to_delivery_phase(vehicle, dt)
        elif state == "align_delivery":
            self.handle_align_delivery_phase(vehicle, dt)
        elif state == "delivery_center":
            self.handle_delivery_center_phase(vehicle, dt)
        elif state == "drop":
            self.handle_drop_phase(vehicle, dt)
        elif state == "delivery_exit":
            self.handle_drive_out_phase_delivery(vehicle, dt)
        elif state == "return_to_garage":
            self.handle_return_to_garage_phase(vehicle, dt)
        else:
            print(
                f"Unbekannter Zustand '{state}' für Fahrzeug {vehicle.getPythonTag('vehicle_id')}. Setze auf 'translate'.")
            vehicle.setPythonTag("order_state", "translate")

        return Task.cont

    # -------------------- Handler für einzelne Phasen --------------------

    def handle_translate_phase(self, vehicle, dt):
        import math
        from panda3d.core import Vec3

        current_order = vehicle.getPythonTag("current_order")
        station_occupied = False
        if current_order is not None and "pickup_station" in current_order:
            pickup_station = current_order["pickup_station"]
            # Login-Mechanismus: Wenn noch niemand eingeloggt ist, logge dieses Fahrzeug ein.
            occupant = pickup_station.getPythonTag("occupied_by")
            if occupant is None:
                pickup_station.setPythonTag("occupied_by", vehicle)
                print(
                    f"Fahrzeug {vehicle.getPythonTag('vehicle_id')} loggt sich an Pickup-Station {pickup_station.getName()}.")
            elif occupant != vehicle:
                station_occupied = True
                print(
                    f"[WARTEN] Pickup-Station {pickup_station.getName()} bereits besetzt durch Fahrzeug {occupant.getPythonTag('vehicle_id')}.")
        # Falls die Station blockiert ist, steht die Basisgeschwindigkeit auf 0.
        base_speed = 1.5 if not station_occupied else 0.0
        adjusted_speed = self.collision_avoidance_adjustment(vehicle, base_speed)

        # Falls noch kein Auftrag zugewiesen, wähle einen neuen Auftrag.
        if current_order is None:
            next_order = self.select_next_order(vehicle)
            if next_order is not None:
                next_order["status"] = "In Bearbeitung"
                next_order["vehicle"] = f"Fahrzeug {vehicle.getPythonTag('vehicle_id')}"
                vehicle.setPythonTag("current_order", next_order)
                print(f"Auftrag {next_order['id']} wird zugewiesen für Fahrzeug {vehicle.getPythonTag('vehicle_id')}.")
            current_order = vehicle.getPythonTag("current_order")

        # Bestimme das Ziel: Verwende den blauen Marker der Pickup-Station oder den allgemeinen blauen Marker.
        if current_order is not None:
            pickup_station = current_order.get("pickup_station")
            if pickup_station in self.station_blue_dots:
                target = self.station_blue_dots[pickup_station].getPos(self.render)
            else:
                target = self.blue_dot.getPos(self.render)
        else:
            target = self.blue_dot.getPos(self.render)

        current_pos = vehicle.getPos(self.render)
        pivot = vehicle.getPythonTag("steering_axis")
        offset_pos = current_pos + vehicle.getQuat(self.render).xform(self.pickup_offset)
        desired_heading_rad = math.atan2(target.getY() - offset_pos.getY(),
                                         target.getX() - offset_pos.getX())
        global_hpr = pivot.getNetTransform().getHpr()
        current_heading_rad = math.radians(global_hpr.getX())
        heading_error = desired_heading_rad - current_heading_rad
        while heading_error > math.pi:
            heading_error -= 2 * math.pi
        while heading_error < -math.pi:
            heading_error += 2 * math.pi

        gain = 1.0
        max_delta = gain * dt
        delta_heading_rad = max(-max_delta, min(max_delta, heading_error))
        self.rotate_around_pivot(vehicle, pivot, math.degrees(delta_heading_rad))

        global_hpr = pivot.getNetTransform().getHpr()
        new_heading_rad = math.radians(global_hpr.getX())
        new_x = current_pos.getX() + adjusted_speed * math.cos(new_heading_rad) * dt
        new_y = current_pos.getY() + adjusted_speed * math.sin(new_heading_rad) * dt
        new_pos = Vec3(new_x, new_y, 0)
        vehicle.setPos(new_pos)

        new_offset_pos = vehicle.getPos(self.render) + vehicle.getQuat(self.render).xform(self.pickup_offset)
        if (target - new_offset_pos).length() < 0.1:
            vehicle.setPythonTag("order_state", "rotate")
        return Task.cont

    def handle_rotate_phase(self, vehicle, dt):
        import math
        # Diese Methode sorgt dafür, dass das Fahrzeug sich dreht, bis sein Pivot-Heading
        # dem gewünschten Winkel entspricht. Wir nehmen hier als Basis den Winkel der
        # grünen Mittellinie der Gabel (fork_center_line) als Referenz.

        # Hole den Pivot-Knoten (z. B. "steering_axis")
        pivot = vehicle.getPythonTag("steering_axis")
        if not pivot:
            print(f"[Rotate] Kein Steering-Axis für Fahrzeug {vehicle.getPythonTag('vehicle_id')} gefunden.")
            return Task.cont

        # Beispielhafter Zielwinkel:
        # Hier gehen wir davon aus, dass die gewünschte Ausrichtung für die Rotation
        # in einer Variablen oder einem festgelegten Wert liegt.
        # Alternativ kannst du den Zielwinkel auch mithilfe eines Markers (etwa der weiß markierten Linie) berechnen.
        # Für dieses Beispiel nehmen wir an, der gewünschte Endwinkel soll dem Winkel der grünen Mittellinie entsprechen.
        try:
            # Wir greifen hier auf den existierenden Node "fork_center_line" zu.
            fork_center_line = vehicle.getPythonTag("fork_center_line")
            if fork_center_line:
                # Der aktuelle globale Heading vom Pivot:
                current_heading = pivot.getNetTransform().getHpr().getX() % 360
                # Nehmen wir an, der Zielwert für die Rotation ist, dass die Gabel genau auf 0° ausgerichtet sein soll:
                target_heading = 0.0
                # Du kannst hier auch andere Logik einbauen, z. B. der Winkel der weißen Linie plus einem Offset.
            else:
                target_heading = 0.0
                current_heading = pivot.getNetTransform().getHpr().getX() % 360
        except Exception as e:
            print(f"[Rotate] Fehler beim Ermitteln des Zielwinkels: {e}")
            return Task.cont

        # Berechne den kleinsten Winkelunterschied (normiert auf [-180, 180])
        error = (target_heading - current_heading + 180) % 360 - 180

        # Debug-Ausgabe
        print(
            f"[Rotate] Fahrzeug {vehicle.getPythonTag('vehicle_id')}: Current Heading = {current_heading:.2f}°, Target = {target_heading:.2f}°, Error = {error:.2f}°")

        # Wenn der Fehler klein genug ist, wechseln wir in die nächste Phase.
        if abs(error) < 1.0:
            vehicle.setPythonTag("order_state", "approach")
            print(f"[Rotate] Fahrzeug {vehicle.getPythonTag('vehicle_id')} beendet Rotation, wechselt in 'approach'.")
            return Task.cont

        # Berechne den Drehschritt: Mit einer festen maximalen Rotationsgeschwindigkeit, z.B. 90°/s.
        turn_speed = 90.0  # Grad pro Sekunde
        max_turn = turn_speed * dt
        turn_angle = max(-max_turn, min(max_turn, error))

        # Wende die Drehung über die Methode rotate_around_pivot an:
        self.rotate_around_pivot(vehicle, pivot, turn_angle)

        return Task.cont

    def handle_approach_phase(self, vehicle, dt):
        current_order = vehicle.getPythonTag("current_order")
        if current_order is not None:
            pickup_station = current_order.get("pickup_station")
            target = pickup_station.getPos(self.render) + Vec3(1.2, 1, 0)
        else:
            target = self.station_green_dot.getPos(self.render) + Vec3(1.2, 1, 0)
        current = vehicle.getPos(self.render)
        error_vec = Vec2(target.getX() - current.getX(), target.getY() - current.getY())
        if error_vec.length() > 0.05:
            direction = error_vec.normalized()
            move_distance = 1.5 * dt
            new_pos = Vec3(current.getX() + direction.getX() * move_distance,
                           current.getY() + direction.getY() * move_distance, target.getZ())
            vehicle.setPos(new_pos)
        else:
            vehicle.setPos(target)
            vehicle.setPythonTag("order_state", "pickup")

    def handle_pickup_phase(self, vehicle, dt):
        fork_node = vehicle.getPythonTag("fork_node")
        current_z = fork_node.getZ()
        target_z = 1.0
        raise_speed = 0.5
        if current_z < target_z:
            fork_node.setZ(min(target_z, current_z + raise_speed * dt))
        else:
            if vehicle.getPythonTag("current_order") is None:
                if self.orders_queue:
                    vehicle.setPythonTag("current_order", self.orders_queue.pop(0))
                else:
                    print(
                        f"Keine verfügbaren Aufträge für Fahrzeug {vehicle.getPythonTag('vehicle_id')}. Überspringe Pickup-Phase.")
                    vehicle.setPythonTag("order_state", "drive_out")
                    return
            if not vehicle.getPythonTag("package_attached"):
                pickup_station = vehicle.getPythonTag("current_order")["pickup_station"]
                self.pickup_package(vehicle, pickup_station)
                vehicle.setPythonTag("package_attached", True)
            if vehicle.getPythonTag("drive_out_target") is None:
                vehicle.setPythonTag("drive_out_target",
                                     vehicle.getPos(self.render) + vehicle.getQuat(self.render).getForward() * 5.0)
            vehicle.setPythonTag("order_state", "drive_out")

    def handle_drive_out_phase(self, vehicle, dt):
        from panda3d.core import Vec3
        fork_node = vehicle.getPythonTag("fork_node")
        current_z = fork_node.getZ()
        if current_z > 0:
            lower_speed = 0.5
            fork_node.setZ(max(0, current_z - lower_speed * dt))
        current_pos = vehicle.getPos(self.render)
        drive_out_target = vehicle.getPythonTag("drive_out_target")
        if drive_out_target is None:
            drive_out_target = current_pos + vehicle.getQuat(self.render).getForward() * 5.0
            vehicle.setPythonTag("drive_out_target", drive_out_target)
        diff = drive_out_target - current_pos
        if diff.length() > 0.1:
            move_distance = 0.5 * dt
            step = diff.normalized() * move_distance
            new_pos = current_pos + step
            new_pos.setZ(0)
            vehicle.setPos(new_pos)
        else:
            # Sobald das Fahrzeug seinen Drive-Out erreicht hat, geben wir den Lock an der Pickup-Station frei
            current_order = vehicle.getPythonTag("current_order")
            if current_order is not None and "pickup_station" in current_order:
                pickup_station = current_order["pickup_station"]
                # Ersetze clearPythonTag durch setPythonTag(..., None) für die Freigabe
                pickup_station.setPythonTag("occupied_by", None)
                print(
                    f"Fahrzeug {vehicle.getPythonTag('vehicle_id')} verlässt Pickup-Station {pickup_station.getName()} und entsperrt diese.")
            vehicle.setPythonTag("order_state", "to_delivery")
            vehicle.setPythonTag("drive_out_target", None)
        return Task.cont

    def handle_to_delivery_phase(self, vehicle, dt):
        import math
        from panda3d.core import Vec3

        current_order = vehicle.getPythonTag("current_order")
        if current_order is None:
            return Task.cont

        # Bestimme das Ziel: Verwende den blauen Marker der Abgabestation (z. B. "Abgabestation 3")
        try:
            target_index = int(current_order.get("ziel", "Abgabestation 1").split()[-1])
        except Exception:
            target_index = 1
        if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
            target = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
        else:
            target = self.abgabe_blue_dots[0].getPos(self.render)

        current_pos = vehicle.getPos(self.render)
        offset_pos = current_pos + vehicle.getQuat(self.render).xform(self.pickup_offset)

        # Prüfe, ob an der Abgabestation bereits ein Fahrzeug in einem blockierenden Zustand ist.
        if self.is_delivery_station_occupied(target, exclude_vehicle=vehicle):
            print(f"[WARTEN] Abgabestation blockiert. Fahrzeug {vehicle.getPythonTag('vehicle_id')} wartet.")
            return Task.cont

        # Berechne den gewünschten Basiswinkel vom Offset-Punkt zum Ziel.
        desired_heading_rad = math.atan2(target.getY() - offset_pos.getY(),
                                         target.getX() - offset_pos.getX())
        pivot = vehicle.getPythonTag("steering_axis")
        global_hpr = pivot.getNetTransform().getHpr()
        current_heading_rad = math.radians(global_hpr.getX())
        heading_error = desired_heading_rad - current_heading_rad
        while heading_error > math.pi:
            heading_error -= 2 * math.pi
        while heading_error < -math.pi:
            heading_error += 2 * math.pi

        gain = 1.0
        max_delta = gain * dt
        delta_heading_rad = max(-max_delta, min(max_delta, heading_error))
        self.rotate_around_pivot(vehicle, pivot, math.degrees(delta_heading_rad))

        global_hpr = pivot.getNetTransform().getHpr()
        new_heading_rad = math.radians(global_hpr.getX())
        adjusted_speed = self.collision_avoidance_adjustment(vehicle, base_speed=1.5)
        new_x = current_pos.getX() + adjusted_speed * math.cos(new_heading_rad) * dt
        new_y = current_pos.getY() + adjusted_speed * math.sin(new_heading_rad) * dt
        new_pos = Vec3(new_x, new_y, current_pos.getZ())
        vehicle.setPos(new_pos)

        new_offset_pos = vehicle.getPos(self.render) + vehicle.getQuat(self.render).xform(self.pickup_offset)
        if (target - new_offset_pos).length() < 0.1:
            vehicle.setPythonTag("order_state", "align_delivery")
        return Task.cont

    def handle_align_delivery_phase(self, vehicle, dt):
        import math

        # 1. Ermittle den Basiszielwinkel aus der weißen Linie der Abgabestation.
        # Wir gehen davon aus, dass self.abgabe_white_line existiert und den globalen Heading liefert.
        try:
            base_target_heading = self.abgabe_white_line.getH(self.render) % 360
        except Exception as e:
            base_target_heading = 90.0
            print(
                f"[Align Delivery] Warning: self.abgabe_white_line nicht gefunden, verwende Default {base_target_heading}°.")

        # 2. Füge den zusätzlichen Versatz von 90° hinzu.
        # Das bedeutet: Der gewünschte End-Heading ist 90° mehr als der von der weißen Linie gemessene Winkel.
        desired_heading = (base_target_heading + 90) % 360

        # 3. Ermittle den aktuellen globalen Heading über den Pivot-Knoten (z. B. steering_axis).
        pivot = vehicle.getPythonTag("steering_axis")
        pivot_hpr = pivot.getNetTransform().getHpr()
        current_heading = pivot_hpr.getX() % 360

        # 4. Berechne den minimalen Winkelunterschied (normiert auf [-180, 180]).
        error = desired_heading - current_heading
        while error > 180:
            error -= 360
        while error < -180:
            error += 360

        print(f"[Align Delivery] Vehicle {vehicle.getPythonTag('vehicle_id')}: "
              f"Current Pivot Heading: {current_heading:.2f}°, "
              f"Desired Heading: {desired_heading:.2f}° (Basis: {base_target_heading:.2f}°+90°), "
              f"Error: {error:.2f}°")

        # 5. Falls der Fehler sehr klein ist (< 1°), gilt die Ausrichtung als abgeschlossen.
        if abs(error) < 1.0:
            # Optional: kleine abschließende Korrektur
            self.rotate_around_pivot(vehicle, pivot, error)
            vehicle.setPythonTag("order_state", "delivery_center")
            print(f"[Align Delivery] Alignment complete for vehicle {vehicle.getPythonTag('vehicle_id')}.")
            return Task.cont

        # 6. Berechne den Drehschritt (proportional, begrenzt durch einen festen maximalen Drehwinkel pro Frame).
        turn_speed = 90.0  # maximale Drehgeschwindigkeit in Grad pro Sekunde
        max_turn = turn_speed * dt
        turn_angle = max(-max_turn, min(max_turn, error))

        # 7. Drehe das Fahrzeug über den Pivot-Knoten.
        self.rotate_around_pivot(vehicle, pivot, turn_angle)

        return Task.cont

    def handle_delivery_center_phase(self, vehicle, dt):
        current_order = vehicle.getPythonTag("current_order")
        if current_order is None:
            return
        delivery_target_str = current_order.get("ziel", "Abgabestation 1")
        try:
            target_index = int(delivery_target_str.split()[-1])
        except ValueError:
            target_index = 1
        if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
            blue_target = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
        else:
            blue_target = self.abgabe_blue_dots[0].getPos(self.render)
        current = vehicle.getPos(self.render)
        target_point = Vec3(blue_target.getX() + 2.3, blue_target.getY() - 0.5, current.getZ())
        print(f"Phase 9: Zielpunkt der Abgabestation für Fahrzeug {vehicle.getPythonTag('vehicle_id')}: {target_point}")
        error_vec = Vec2(target_point.getX() - current.getX(), target_point.getY() - current.getY())
        tolerance = 0.05
        move_distance = 1.5 * dt
        if error_vec.length() > tolerance:
            direction = error_vec.normalized()
            new_pos = Vec3(current.getX() + direction.getX() * move_distance,
                           current.getY() + direction.getY() * move_distance, current.getZ())
            vehicle.setPos(new_pos)
            print(f"Phase 9: Fahrzeug {vehicle.getPythonTag('vehicle_id')} bewegt sich von {current} nach {new_pos}")
        else:
            vehicle.setPos(target_point)
            print(f"Phase 9: Fahrzeug {vehicle.getPythonTag('vehicle_id')} hat den Zielpunkt erreicht.")
            vehicle.setPythonTag("order_state", "drop")
        fork_node = vehicle.getPythonTag("fork_node")
        current_fork_z = fork_node.getZ()
        if current_fork_z < 1.0:
            new_fork_z = min(1.0, current_fork_z + 0.5 * dt)
            fork_node.setZ(new_fork_z)
            print(
                f"Phase 9: Gabel wird angehoben für Fahrzeug {vehicle.getPythonTag('vehicle_id')} (Z = {new_fork_z}).")

    def handle_drop_phase(self, vehicle, dt):
        # Falls das Fahrzeug ein Paket trägt, wird dieses abgesetzt.
        if vehicle.getPythonTag("package_attached"):
            self.drop_cargo(vehicle)
            print(f"Phase 10: Paket abgesetzt für Fahrzeug {vehicle.getPythonTag('vehicle_id')}")
            vehicle.setPythonTag("package_attached", False)
        else:
            # Falls die Gabel noch abgesenkt werden muss:
            fork_node = vehicle.getPythonTag("fork_node")
            current_z = fork_node.getZ()
            if current_z > 0:
                lower_speed = 0.5
                fork_node.setZ(max(0, current_z - lower_speed * dt))
            print(f"Phase 10: Dropoff abgeschlossen für Fahrzeug {vehicle.getPythonTag('vehicle_id')}")

        # Setze den Zustand nun auf "delivery_exit", damit das Fahrzeug aus dem Lieferbereich herausfährt.
        vehicle.setPythonTag("order_state", "delivery_exit")
        # Optional: den Auftrag als "Abgegeben" markieren und löschen.
        current_order = vehicle.getPythonTag("current_order")
        if current_order is not None:
            current_order["status"] = "Abgegeben"
            current_order["delivered_at"] = self.sim_clock
        vehicle.clearPythonTag("current_order")

        return Task.cont

    def handle_drive_out_phase_delivery(self, vehicle, dt):
        from panda3d.core import Vec3
        fork_node = vehicle.getPythonTag("fork_node")
        current_z = fork_node.getZ()
        if current_z > 0:
            lower_speed = 0.5
            fork_node.setZ(max(0, current_z - lower_speed * dt))
        current_pos = vehicle.getPos(self.render)
        drive_out_target = vehicle.getPythonTag("drive_out_target")
        if drive_out_target is None:
            drive_out_target = current_pos + vehicle.getQuat(self.render).getForward() * 5.0
            vehicle.setPythonTag("drive_out_target", drive_out_target)
        diff = drive_out_target - current_pos
        if diff.length() > 0.1:
            move_distance = 0.5 * dt
            step = diff.normalized() * move_distance
            new_pos = current_pos + step
            new_pos.setZ(0)
            vehicle.setPos(new_pos)
        else:
            # Sobald das Fahrzeug seinen Drive-Out im Lieferbereich erreicht hat, geben wir den Lock frei
            current_order = vehicle.getPythonTag("current_order")
            if current_order is not None:
                try:
                    target_index = int(current_order.get("ziel", "Abgabestation 1").split()[-1])
                except Exception:
                    target_index = 1
                if 0 <= target_index - 1 < len(self.abgabe_stations):
                    delivery_station = self.abgabe_stations[target_index - 1]
                else:
                    delivery_station = self.abgabe_stations[0]
                # Freigabe des Locks an der Delivery-Station
                delivery_station.setPythonTag("occupied_by", None)
                print(
                    f"Fahrzeug {vehicle.getPythonTag('vehicle_id')} verlässt Delivery-Station {delivery_station.getName()} und entsperrt diese.")
            vehicle.setPythonTag("order_state", "translate")
            vehicle.setPythonTag("drive_out_target", None)
            print(
                f"Fahrzeug {vehicle.getPythonTag('vehicle_id')} hat den Lieferbereich verlassen und wechselt in 'translate'.")
        return Task.cont

    def handle_phase11(self, vehicle, dt):
        current_order = vehicle.getPythonTag("current_order")
        if vehicle.getPythonTag("last_delivery_marker") is not None:
            target_point = vehicle.getPythonTag("last_delivery_marker")
        else:
            delivery_target_str = current_order.get("ziel", "Abgabestation 1")
            try:
                target_index = int(delivery_target_str.split()[-1])
            except ValueError:
                target_index = 1
            if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
                target_point = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
            else:
                target_point = self.abgabe_blue_dots[0].getPos(self.render)
        print(f"Phase 11: Zielpunkt (blauer Marker) für Fahrzeug {vehicle.getPythonTag('vehicle_id')}: {target_point}")
        current_pos = vehicle.getPos(self.render)
        diff = target_point - current_pos
        if diff.length() > 0.1:
            move_distance = 0.5 * dt
            step = diff.normalized() * move_distance
            new_pos = current_pos + step
            vehicle.setPos(new_pos)
            print(
                f"Phase 11: Fahrzeug {vehicle.getPythonTag('vehicle_id')} fährt aus der Station, neue Position: {new_pos}")
        else:
            vehicle.setPos(target_point)
            print(
                f"Phase 11: Fahrzeug {vehicle.getPythonTag('vehicle_id')} hat den blauen Marker erreicht. Nächster Auftrag wird gestartet.")
            vehicle.setPythonTag("order_state", "next_order")

    def handle_return_to_garage_phase(self, vehicle, dt):
        garage_target = vehicle.getPythonTag("garage_target")
        if garage_target is None:
            garage_target = self.garagen_parking_points[0]
        current_pos = vehicle.getPos(self.render)
        diff = garage_target - current_pos
        if diff.length() > 0.1:
            move_distance = 1.0 * dt
            new_pos = current_pos + diff.normalized() * move_distance
            new_pos.setZ(0)
            vehicle.setPos(new_pos)
        else:
            if vehicle.hasPythonTag("start_heading"):
                vehicle.setH(vehicle.getPythonTag("start_heading"))
            vehicle.setPythonTag("order_state", "idle")
            vehicle.setPythonTag("standby_pending", False)
            print(f"Fahrzeug {vehicle.getPythonTag('vehicle_id')} ist in der Garage (Standby).")

    def collect_sensor_data(self, vehicle, sensor_range=5, grid_resolution=0.5):
        """
        Erzeugt ein einfaches 2D-Occupancy-Grid, das den Bereich um das Fahrzeug simuliert.

        Parameter:
          sensor_range: Radius (in Welt-Einheiten) um das Fahrzeug.
          grid_resolution: Größe der einzelnen Zellen im Grid.

        Rückgabe:
          Ein NumPy-Array (2D) mit 0 (frei) als Platzhalter.
        """
        import numpy as np
        grid_size = int((sensor_range * 2) / grid_resolution)
        sensor_grid = np.zeros((grid_size, grid_size))
        # --- Hier kannst du später echte Kollisionsabfragen oder Ray-Casting integrieren ---
        return sensor_grid

    def compute_ideal_steering_correction(self, vehicle):
        """
        Berechnet einen idealen Korrekturwinkel (in Grad) für die Navigation in der 'translate'-Phase.
        Es wird ein vereinfachtes Modell genutzt, das den Unterschied zwischen dem gewünschten und dem aktuellen
        Heading (über die Fahrzeug-Steuerachse) ermittelt.
        """
        import math

        current_order = vehicle.getPythonTag("current_order")
        if current_order is not None and "pickup_station" in current_order:
            pickup_station = current_order["pickup_station"]
            if pickup_station in self.station_blue_dots:
                target = self.station_blue_dots[pickup_station].getPos(self.render)
            else:
                target = self.blue_dot.getPos(self.render)
        else:
            target = self.blue_dot.getPos(self.render)

        current_pos = vehicle.getPos(self.render)
        # Bestimme einen Offset-Punkt, basierend auf der bereits existierenden pickup_offset
        offset_pos = current_pos + vehicle.getQuat(self.render).xform(self.pickup_offset)
        # Berechne den gewünschten Heading-Winkel (in Radiant): Richtung von offset_pos zu target
        desired_heading_rad = math.atan2(target.getY() - offset_pos.getY(),
                                         target.getX() - offset_pos.getX())

        # Hole den aktuellen Heading-Wert vom Steuerachsen-Node (pivot)
        pivot = vehicle.getPythonTag("steering_axis")
        global_hpr = pivot.getNetTransform().getHpr()
        current_heading_rad = math.radians(global_hpr.getX())

        ideal_correction_rad = desired_heading_rad - current_heading_rad
        # Winkelbereich anpassen [-pi, pi]
        while ideal_correction_rad > math.pi:
            ideal_correction_rad -= 2 * math.pi
        while ideal_correction_rad < -math.pi:
            ideal_correction_rad += 2 * math.pi

        return math.degrees(ideal_correction_rad)

    def compute_avoidance_angle(self, current_vehicle, safe_distance=3.0):
        """
        Berechnet einen zusätzlichen Ausweichwinkel (in Grad) basierend auf den
        Positionen anderer Fahrzeuge. Fahrzeuge, die sehr nah sind, sollen einen
        höheren Einfluss haben. Der Rückgabewert wird mit einem Gewichtungsfaktor
        multipliziert, sodass der Ausweichimpuls moderat bleibt.
        """
        import math
        from panda3d.core import Vec2

        current_pos = current_vehicle.getPos(self.render)
        avoidance_vector = Vec2(0, 0)

        # Schleife über alle Fahrzeuge (außer dem eigenen)
        for other in self.garage_vehicles:
            if other == current_vehicle:
                continue
            other_pos = other.getPos(self.render)
            diff = Vec2(current_pos.getX() - other_pos.getX(),
                        current_pos.getY() - other_pos.getY())
            dist = diff.length()
            if dist > 0 and dist < safe_distance:
                # Je näher das Fahrzeug, desto größer der Einfluss (gewichtete Summe)
                weight = (safe_distance - dist) / safe_distance
                avoidance_vector += diff.normalized() * weight

        # Falls kein Fahrzeug in der Nähe ist, wird kein Ausweichwinkel angewendet.
        if avoidance_vector.length() == 0:
            return 0.0

        # Berechne den Winkel, den der resultierende Ausweichvektor vorgibt.
        avoidance_angle = math.degrees(math.atan2(avoidance_vector.getY(), avoidance_vector.getX()))
        # Mit einem Faktor abschwächen, um den Einfluss zu mildern.
        weight_factor = 0.5  # Passe diesen Faktor bei Bedarf an (0 = kein Ausweichen, 1 = voll)
        return avoidance_angle * weight_factor

    def log_training_sample(self, sensor_data, ideal_angle):
        """
        Speichert ein Trainingssample bestehend aus den gesammelten Sensorwerten und dem idealen Korrekturwinkel.
        """
        self.training_data.append((sensor_data.copy(), ideal_angle))
        # Optional: Gib eine Debug-Ausgabe aus, um das Logging zu überwachen.
        print(
            f"[LOG] Trainingssample gespeichert: Ideal Correction = {ideal_angle:.2f}°, Sensor Shape = {sensor_data.shape}")

    def apply_safety_rules(self, vehicle, sensor_data, model_delta_angle, ideal_correction):
        """
        Kombiniert den vom Modell (model_delta_angle) und den ideal berechneten Korrekturwert (ideal_correction)
        nur dann mit einem festen Sicherheitswert, wenn die Sensordaten einen kritischen Occupancy-Level anzeigen.

        Falls der Occupancy-Level niedrig ist, wird ausschließlich der ideal vorhandene Korrekturwert verwendet.
        """
        import numpy as np
        # Beispiel: Untersuche die mittlere Zeile des sensor_data-Grids als Indikator für frontale Hindernisse
        middle_row = sensor_data[sensor_data.shape[0] // 2]
        occupancy_level = np.sum(middle_row)

        # Definiere einen kritischen Schwellenwert (diesen Wert ggf. anpassen)
        threshold = 1.0

        if occupancy_level > threshold:
            print(
                f"[RULE] Kritischer Occupancy-Level = {occupancy_level:.2f} erkannt. Sicherheitskorrektur wird angewendet.")
            # Hier legen wir fest, dass in kritischen Situationen der Sicherheitswert stärker gewichtet wird.
            safety_correction = 15.0  # z. B. 15° als feste Korrektur (Wert anpassen)
            # Gewichteter Ansatz: Sicherheitskorrektur dominiert, während ein kleiner Anteil des idealen Wertes einfließt.
            final_angle = 0.7 * safety_correction + 0.3 * ideal_correction
        else:
            # Wenn kein kritischer Wert vorliegt, einfach den ideal berechneten Korrekturwert verwenden.
            final_angle = ideal_correction

        return final_angle

    def collision_avoidance_adjustment(self, current_vehicle, base_speed, safe_distance=3.0):
        """
        Berechnet eine angepasste Geschwindigkeit für ein Fahrzeug (current_vehicle), sodass
        dessen Basisgeschwindigkeit (base_speed) entsprechend reduziert wird, wenn andere Fahrzeuge
        in der Nähe sind. Wenn der Abstand zu einem anderen Fahrzeug unter 1 Einheit liegt, wird
        die Geschwindigkeit auf 0 gesetzt.

        Parameter:
          current_vehicle: Das Fahrzeug, dessen Geschwindigkeit angepasst werden soll.
          base_speed: Die Basisgeschwindigkeit (ohne Kollisionseffekt).
          safe_distance: Der Abstand, unterhalb dessen Fahrzeuge ihre Geschwindigkeit reduzieren.

        Rückgabe:
          Die angepasste Geschwindigkeit.
        """
        current_pos = current_vehicle.getPos(self.render)
        adjusted_speed = base_speed
        for veh in self.garage_vehicles:
            if veh == current_vehicle:
                continue
            other_pos = veh.getPos(self.render)
            distance = (current_pos - other_pos).length()
            if distance < safe_distance:
                # Wenn Fahrzeuge extrem nahe kommen, wird die Geschwindigkeit auf 0 gesetzt.
                if distance < 1.0:
                    candidate_speed = 0.0
                else:
                    # Lineare Reduktion: Je näher das Fahrzeug, desto geringer die erlaubte Geschwindigkeit.
                    candidate_speed = base_speed * (distance / safe_distance)
                # Wähle den minimalen Wert
                if candidate_speed < adjusted_speed:
                    adjusted_speed = candidate_speed
                print(f"[Collision Avoidance] Fahrzeug {current_vehicle.getPythonTag('vehicle_id')} "
                      f"reduziert Geschwindigkeit auf {adjusted_speed:.2f} (Abstand zu Fahrzeug {veh.getPythonTag('vehicle_id')}: {distance:.2f})")
        return adjusted_speed

    def is_station_occupied(self, station, exclude_vehicle=None, occupancy_threshold=1.0):
        """
        Prüft, ob sich bereits ein Fahrzeug an der gegebenen Station (z. B. Pickup‑Station)
        befindet. Dabei wird als Zielpunkt zumeist der blaue Marker genutzt, der der Station
        zugeordnet ist. Das Fahrzeug exclude_vehicle (z. B. das aktuell agierende Fahrzeug)
        wird dabei nicht berücksichtigt.
        """
        # Falls ein blauer Marker vorhanden ist, nutze dessen Position als Zielort:
        if hasattr(self, 'station_blue_dots') and station in self.station_blue_dots:
            station_pos = self.station_blue_dots[station].getPos(self.render)
        else:
            station_pos = station.getPos(self.render)
        for veh in self.garage_vehicles:
            if veh == exclude_vehicle:
                continue
            if (veh.getPos(self.render) - station_pos).length() < occupancy_threshold:
                return True
        return False

    def is_delivery_station_occupied(self, target_pos, exclude_vehicle=None, occupancy_threshold=1.0):
        """
        Prüft, ob sich ein Fahrzeug in der Nähe der Abgabestation (target_pos) befindet,
        welches in einer Lieferphase (z. B. drop, delivery_center oder align_delivery) ist oder noch ein Paket
        transportiert (package_attached = True). Das Fahrzeug exclude_vehicle (z. B. das aktuell anfahrende Fahrzeug)
        wird dabei nicht berücksichtigt.
        """
        for veh in self.garage_vehicles:
            if veh == exclude_vehicle:
                continue
            # Hole den aktuellen Zustand und ob ein Paket noch angebracht ist.
            state = veh.getPythonTag("order_state")
            package_attached = veh.getPythonTag("package_attached")
            if state in ["drop", "delivery_center", "align_delivery"] or package_attached:
                if (veh.getPos(self.render) - target_pos).length() < occupancy_threshold:
                    return True
        return False

    def check_collisions(self):
        """
        Ermittelt alle Fahrzeugpaare, die näher als collision_threshold (z.B. 1 Einheit)
        beieinander liegen – also als kollidierend gelten.
        """
        collision_threshold = 1.0  # Fahrzeuge gelten als kollidierend, wenn ihr Abstand unter 1 Einheit liegt
        collisions = []
        for i in range(len(self.garage_vehicles)):
            veh1 = self.garage_vehicles[i]
            pos1 = veh1.getPos(self.render)
            for j in range(i + 1, len(self.garage_vehicles)):
                veh2 = self.garage_vehicles[j]
                pos2 = veh2.getPos(self.render)
                if (pos1 - pos2).length() < collision_threshold:
                    collisions.append((veh1, veh2))
        return collisions

    def update_rl_on_collisions(self):
        """
        Prüft regelmäßig, ob Fahrzeuge kollidieren. Für jedes kollidierende Fahrzeugpaar
        wird die Kollisionsdauer ermittelt. Liegt diese Dauer über 5 Sekunden,
        wird der Zustand der Fahrzeuge auf "drive_out" gesetzt – also sollen sie dann
        einfach weiterfahren.
        """
        collisions = self.check_collisions()
        current_time = self.sim_clock

        # Erstelle oder verwende ein Dictionary, um die Startzeiten der Kollisionspaare zu speichern.
        if not hasattr(self, "collision_start_times"):
            self.collision_start_times = {}

        # Erstelle eine Menge der aktuell kollidierenden Fahrzeugpaare (als frozenset, um die Reihenfolge zu ignorieren)
        current_collision_keys = set()
        for veh1, veh2 in collisions:
            key = frozenset({veh1, veh2})
            current_collision_keys.add(key)
            if key not in self.collision_start_times:
                self.collision_start_times[key] = current_time
            else:
                duration = current_time - self.collision_start_times[key]
                if duration > 5.0:
                    # Wenn die Fahrzeuge länger als 5 Sekunden kollidieren, werden sie "unblocked"
                    if veh1.getPythonTag("order_state") != "drive_out":
                        print(
                            f"[COLLISION] Fahrzeug {veh1.getPythonTag('vehicle_id')} kollidiert seit {duration:.1f}s – Losfahren!")
                        veh1.setPythonTag("order_state", "drive_out")
                    if veh2.getPythonTag("order_state") != "drive_out":
                        print(
                            f"[COLLISION] Fahrzeug {veh2.getPythonTag('vehicle_id')} kollidiert seit {duration:.1f}s – Losfahren!")
                        veh2.setPythonTag("order_state", "drive_out")
                    # Nach dem Unblocken löschen wir den Eintrag für diese kollidierende Fahrzeugpaar.
                    if key in self.collision_start_times:
                        del self.collision_start_times[key]

        # Bereinige Einträge, die nicht mehr aktuell sind.
        keys_to_remove = [key for key in self.collision_start_times if key not in current_collision_keys]
        for key in keys_to_remove:
            del self.collision_start_times[key]

        # Falls du hier noch RL-Updates vornehmen möchtest, kannst du an dieser Stelle zusätzliche Logik einfügen.


class RLAgent:
    def __init__(self, state_bins, action_space, learning_rate=0.1, discount_factor=0.9, epsilon=0.2):
        """
        state_bins: Tuple oder Liste, um kontinuierliche Zustände zu diskretisieren (z.B. (max_distance, num_bins))
        action_space: Liste diskreter Aktionen (z.B. [0, 1, 2] --> 0: keine Bremsung, 1: leicht, 2: stark)
        """
        self.state_bins = state_bins
        self.action_space = action_space
        self.lr = learning_rate
        self.gamma = discount_factor
        self.epsilon = epsilon
        # Initialisiere Q-Tabelle als Dictionary: key: (discretisierter_state), value: Liste von Q-Werten pro Aktion
        self.q_table = {}

    def discretize_state(self, state):
        """
        Nimmt einen Zustandsvektor (z.B. [distance, speed]) und gibt einen diskreten Zustand zurück.
        Hier ein Beispiel: Falls state[0] = Abstand und state[1] = Geschwindigkeit.
        """
        # Beispiel: Wir nehmen an, dass state_bins = ((max_distance, num_bins), (max_speed, num_bins))
        discrete_state = []
        for i, (max_val, bins) in enumerate(self.state_bins):
            # Begrenze state[i] um max_val:
            val = min(state[i], max_val)
            bin_size = max_val / bins
            discrete_state.append(int(val // bin_size))
        return tuple(discrete_state)

    def select_action(self, state):
        discrete_state = self.discretize_state(state)
        if discrete_state not in self.q_table:
            self.q_table[discrete_state] = [0.0 for _ in self.action_space]
        # Epsilon-greedy Auswahl:
        if random.random() < self.epsilon:
            return random.choice(self.action_space)
        else:
            q_values = self.q_table[discrete_state]
            return self.action_space[np.argmax(q_values)]

    def update(self, state, action, reward, next_state):
        s = self.discretize_state(state)
        s_next = self.discretize_state(next_state)
        if s not in self.q_table:
            self.q_table[s] = [0.0 for _ in self.action_space]
        if s_next not in self.q_table:
            self.q_table[s_next] = [0.0 for _ in self.action_space]
        a_index = self.action_space.index(action)
        # Q-Learning Update-Regel:
        best_next = max(self.q_table[s_next])
        self.q_table[s][a_index] += self.lr * (reward + self.gamma * best_next - self.q_table[s][a_index])

    def is_station_occupied(self, station, exclude_vehicle=None, occupancy_threshold=1.0):
        # Bestimme den Zielpunkt der Station – falls über station_blue_dots verfügbar.
        if hasattr(self, 'station_blue_dots') and station in self.station_blue_dots:
            station_pos = self.station_blue_dots[station].getPos(self.render)
        else:
            station_pos = station.getPos(self.render)
        for veh in self.garage_vehicles:
            if veh == exclude_vehicle:
                continue
            current_order = veh.getPythonTag("current_order")
            if current_order is not None and current_order.get("pickup_station") == station:
                # Blockiere die Station, solange das Fahrzeug nicht den Zustand erreicht hat,
                # der anzeigt, dass es die Station verlassen hat.
                if veh.getPythonTag("order_state") not in ["to_delivery", "idle", "next_order"]:
                    return True
            # Zusätzlich: Blockiere, wenn ganz nahe am Station-Zielpunkt
            if (veh.getPos(self.render) - station_pos).length() < occupancy_threshold:
                return True
        return False

    def is_delivery_station_occupied(self, station, exclude_vehicle=None, occupancy_threshold=1.0):
        occupant = station.getPythonTag("occupied_by")
        if occupant is not None and occupant != exclude_vehicle:
            return True
        # Optional: Falls du noch eine physikalische Näheprüfung implementieren möchtest, kannst du dies ergänzen.
        return False


if __name__ == "__main__":
    # Wichtig: setze auf Windows die Startmethode auf "spawn"
    multiprocessing.set_start_method('spawn')

    # Erzeuge eine Queue, auch wenn sie später eventuell neu erstellt wird, wenn "G" gedrückt wird.
    graph_q = Queue()
    app = LagerSimulation(graph_q)
    app.run()

    # Beim Schließen der Simulation den Graphprozess ggf. beenden
    if app.graph_process is not None:
        app.graph_process.terminate()
        app.graph_process.join()