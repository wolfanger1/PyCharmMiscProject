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

from environment_visualization import EnvironmentVisualizer


class LagerSimulation(ShowBase):
    def __init__(self, graph_queue=None):
        # Basisinitialisierung und Simulationsvariablen
        super().__init__()
        self.paused = False
        self.sim_clock = 0.0
        self.speed_factor = 1.0
        self.current_speed = 1.5
        self.state_timer = 0.0

        # Kennzahlen (KPIs)
        self.delivered_packages = 0
        self.max_overall_wait_time = 0.0
        self.total_dwell_time = 0.0
        self.picked_up_count = 0
        self.total_delivery_time = 0.0
        self.total_delivery_count = 0
        self.max_overall_delivery_time = 0.0

        # Paket- und Auftragsverwaltung
        self.pickup_packages = {}  # {Station: (Paket, Spawn-Zeit, Timer-Node)}
        self.last_removed = {}  # Letzte Entfernungszeit pro Station
        self.cargos = {}  # Fahrzeug -> transportiertes Paket
        self.occupied_pickups = set()  # Bereits belegte Annahmestationen
        self.graph_data = []  # (Sim-Zeit, Pakete/Minute, durchschnittliche Liegedauer, Lieferzeit)
        self.graph_opened = False# Zum Beispiel: 0.5 Einheiten in X‑Richtung (vorne) und 0 in Y, 0 in Z.
        self.pickup_offset = Vec3(0.5, -0.5, 0)


        self.orders = {}
        self.orders_queue = []
        self.next_order_id = 1

        # Fenster und UI für Auftragsübersicht
        self.order_win = None
        self.order_tree = None

        # Graph-Prozess (für interaktive Graphen via PyQt)
        self.graph_process = None
        self.graph_queue = None

        # Tkinter-Grundfenster: Es wird im Hintergrund ausgeführt.
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()

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

        # Verbindungslinien
        self.env_viz.connect_annahme_abgabe_blue_dots(color=LColor(1, 1, 1, 1), thickness=2.0)

        self.env_viz.connect_garagen_blue_dots(line_color=LColor(1, 1, 1, 1), thickness=2.0,
                                               text_color=LColor(0, 0, 1, 1))
        self.env_viz.connect_annahme_stations(color=LColor(1, 1, 1, 1), thickness=2.0)
        self.env_viz.connect_abgabe_stations(color=LColor(1, 1, 1, 1), thickness=2.0)

        # Erzeuge den fixierten blauen Punkt (wird nur einmal erzeugt)
        self.fixed_blue_dot = self.env_viz.create_fixed_blue_dot()
        # Erstelle die Verbindungslinie, die den blauen Marker der 10. Abgabestation mit dem fixierten Punkt verbindet
        self.fixed_connection_line = self.env_viz.create_fixed_connection_line()
        # Erzeuge die Verbindungslinie von dem fixierten Punkt zur 5. Garage.
        self.garage5_connection_line = self.env_viz.create_garage5_connection_line()

        self.first_garage_to_10_annahme_connection = self.env_viz.create_connection_line_first_garage_to_10_annahme()

        self.yellow_station_points = self.env_viz.create_yellow_station_points(offset=3.0, scale=0.1)
        self.yellow_abgabe_points = self.env_viz.create_yellow_abgabe_points(offset=3.0, scale=0.1)
        self.yellow_garage_points = self.env_viz.create_yellow_garage_points(offset=3.0, scale=0.1)

        # --- Aufbau der Umgebung ---
        # Ursprung und Kamera
        self.cam.setPos(11, -80, 40)
        self.cam.lookAt(11, 30, 0)


        # Für jede Annahmestation ein Paket spawnen
        for station in self.annahme_stations:
            self.spawn_package_at_station(station)

        # Fahrzeuge in den Garagen erstellen (insgesamt 5 Fahrzeuge)
        self.create_garage_vehicles()  # Fahrzeuge werden hier erzeugt – sorge dafür, dass self.garage_vehicles gesetzt wird.

        # Zusätzliche Testvariablen
        self.first_vehicle_order_state = "idle"
        self.attached_package = None
        self.current_order = None

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

        # Berechne aktuelle Lieferzeiten für Fahrzeuge, die ein Paket tragen
        current_delivery_time = 0.0
        for veh in self.garage_vehicles:
            if veh.getPythonTag("package_attached"):
                ds = veh.getPythonTag("delivery_start_time")
                if ds:
                    elapsed_delivery = self.sim_clock - ds
                    current_delivery_time = max(current_delivery_time, elapsed_delivery)
        avg_delivery_time = self.total_delivery_time / self.total_delivery_count if self.total_delivery_count > 0 else 0.0

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
        return task.cont

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

    def close_order_window(self):
        if self.order_win is not None:
            self.order_win.withdraw()

    #-------Fahrzeugsteuerung(Bedienfenster)-------
    def show_vehicle_control(self):
        # Falls das Fenster bereits existiert, bringe es einfach in den Vordergrund,
        # ohne die Radiobuttons neu zu initialisieren.
        if hasattr(self, "control_win") and self.control_win.winfo_exists():
            self.control_win.deiconify()
            self.control_win.lift()
            self.control_win.focus_force()
            return

        # Erstelle das Kontrollfenster als Toplevel des persistenten tk_root.
        self.control_win = tk.Toplevel(self.tk_root)
        self.control_win.title("Fahrzeugsteuerung")
        # Beim Schließen soll das Fenster nicht zerstört, sondern nur versteckt werden
        self.control_win.protocol("WM_DELETE_WINDOW", self.control_win.withdraw)
        # Sorge dafür, dass das Fenster initial über allem liegt
        self.control_win.attributes("-topmost", True)
        self.control_win.after(100, lambda: self.control_win.attributes("-topmost", False))

        # Erzeuge das Dictionary für die StringVar-Zuordnungen für die Fahrzeuge.
        self.vehicle_state_vars = {}
        row = 0
        for veh in self.garage_vehicles:
            frame = tk.Frame(self.control_win)
            frame.grid(row=row, column=0, sticky="w", padx=5, pady=2)
            vid = veh.getPythonTag("vehicle_id")
            label = tk.Label(frame, text=f"Fahrzeug {vid}")
            label.pack(side=tk.LEFT)
            # Initialisiere die Radiobutton-Variable anhand des aktuellen Fahrzeugzustandes.
            state = veh.getPythonTag("order_state")
            if state is None:
                state = "idle"
            var = tk.StringVar(value=state)
            self.vehicle_state_vars[veh] = var
            rb_active = tk.Radiobutton(frame, text="Aufträge bearbeiten", variable=var, value="translate")
            rb_active.pack(side=tk.LEFT)
            rb_standby = tk.Radiobutton(frame, text="Standby", variable=var, value="idle")
            rb_standby.pack(side=tk.LEFT)
            row += 1
        update_btn = tk.Button(self.control_win, text="Übernehmen", command=self.update_vehicle_control)
        update_btn.grid(row=row, column=0, pady=5)

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

    # ---------------3. Umgebungsaufbau & Visualisierungsaufbau---------------
    def update_cable(self, task):
        # Verwende die simulative Zeit, die bereits in update_sim_clock hochgezählt wird
        t = self.sim_clock
        new_height = 0.5 + 0.5 * math.sin(t * 2.0)
        self.fork_node.setZ(new_height)
        return Task.cont

    def create_garage_vehicles(self):
        # Stelle sicher, dass self.garagen_parking_points bereits gesetzt wurde
        self.garage_vehicles = []
        vehicle_id_counter = 1
        for park in self.garagen_parking_points:
            # Erzeuge Fahrzeug – hierbei wird davon ausgegangen, dass die Methode create_vehicle existiert.
            veh = self.create_vehicle(park_point=park)
            veh.setH(veh.getH() + 180)
            intersection = Vec3(0.5, 0.05, 1.0)
            newPos = park - veh.getQuat().xform(intersection)
            newPos.setZ(0)
            veh.setPos(newPos)
            # Setze Fahrzeug-Tags
            veh.setPythonTag("current_order", None)
            veh.setPythonTag("order_state", "idle")
            veh.setPythonTag("package_attached", False)
            veh.setPythonTag("vehicle_id", vehicle_id_counter)
            veh.setPythonTag("garage_target", park)
            veh.setPythonTag("start_heading", veh.getH())
            vehicle_id_counter += 1
            self.garage_vehicles.append(veh)

            # Markierung für das Fahrzeug (z.B. als Standort in der Garage)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.2)
            marker.setColor(LColor(0, 0, 1, 1))
            marker.setPos(park.getX(), park.getY(), 0)
            marker.reparentTo(self.render)

            # Fahrzeugnummer als Text – Suche nach Mast oder hänge direkt an das Fahrzeug
            mast = veh.find("**/mast")
            if not mast.isEmpty():
                tn = TextNode("vehicle_number")
                tn.setText(str(veh.getPythonTag("vehicle_id")))
                tn.setTextColor(LColor(0, 0, 0, 1))
                tn.setAlign(TextNode.ACenter)
                text_np = mast.attachNewNode(tn)
                text_np.setPos(intersection.x, intersection.y, intersection.z + 0.2)
                text_np.setScale(0.8)
                text_np.setHpr(0, 0, 0)
            else:
                tn = TextNode("vehicle_number")
                tn.setText(str(veh.getPythonTag("vehicle_id")))
                tn.setTextColor(LColor(0, 0, 0, 1))
                tn.setAlign(TextNode.ACenter)
                text_np = veh.attachNewNode(tn)
                text_np.setPos(0, 1.2, 1.5)
                text_np.setScale(0.8)
                text_np.setHpr(0, 0, 0)
            # Starte den Fahrzeugtask (sofern diese Logik besteht)
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

        # Bestimme zufällig eine Abgabestation als Ziel
        if hasattr(self, "abgabe_stations") and self.abgabe_stations:
            target_index = random.randint(1, len(self.abgabe_stations))
        else:
            target_index = 1

        # Erstelle den Auftrag zur Annahmestation
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
        spawn_delay = 5.0  # 5 Sekunden Verzögerung zwischen Spawns
        for station in self.annahme_stations:
            # Wenn aktuell kein Paket an der Station ist
            if station not in self.pickup_packages:
                last_time = self.last_removed.get(station, self.sim_clock)
                # Prüfe, ob seit der letzten Entnahme mindestens 5 Sekunden vergangen sind
                if (self.sim_clock - last_time) >= spawn_delay:
                    self.spawn_package_at_station(station)
        return Task.cont

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
        if self.order_win is not None:
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
        # Falls das Fenster bereits existiert, bringe es einfach in den Vordergrund,
        # ohne die Radiobuttons neu zu initialisieren.
        if hasattr(self, "control_win") and self.control_win.winfo_exists():
            self.control_win.deiconify()
            self.control_win.lift()
            self.control_win.focus_force()
            return

        # Erstelle das Kontrollfenster als Toplevel des persistenten tk_root.
        self.control_win = tk.Toplevel(self.tk_root)
        self.control_win.title("Fahrzeugsteuerung")
        # Beim Schließen soll das Fenster nicht zerstört, sondern nur versteckt werden
        self.control_win.protocol("WM_DELETE_WINDOW", self.control_win.withdraw)
        # Sorge dafür, dass das Fenster initial über allem liegt
        self.control_win.attributes("-topmost", True)
        self.control_win.after(100, lambda: self.control_win.attributes("-topmost", False))

        # Erzeuge das Dictionary für die StringVar-Zuordnungen für die Fahrzeuge.
        self.vehicle_state_vars = {}
        row = 0
        for veh in self.garage_vehicles:
            frame = tk.Frame(self.control_win)
            frame.grid(row=row, column=0, sticky="w", padx=5, pady=2)
            vid = veh.getPythonTag("vehicle_id")
            label = tk.Label(frame, text=f"Fahrzeug {vid}")
            label.pack(side=tk.LEFT)
            # Initialisiere die Radiobutton-Variable anhand des aktuellen Fahrzeugzustandes.
            state = veh.getPythonTag("order_state")
            if state is None:
                state = "idle"
            var = tk.StringVar(value=state)
            self.vehicle_state_vars[veh] = var
            rb_active = tk.Radiobutton(frame, text="Aufträge bearbeiten", variable=var, value="translate")
            rb_active.pack(side=tk.LEFT)
            rb_standby = tk.Radiobutton(frame, text="Standby", variable=var, value="idle")
            rb_standby.pack(side=tk.LEFT)
            row += 1
        update_btn = tk.Button(self.control_win, text="Übernehmen", command=self.update_vehicle_control)
        update_btn.grid(row=row, column=0, pady=5)

    def vehicle_order_task(self, vehicle, task):
        # Berechne das Zeitintervall (dt)
        dt = ClockObject.getGlobalClock().getDt() * self.speed_factor
        state = vehicle.getPythonTag("order_state")

        # Zustandsbasierte Weiterleitung an die jeweiligen Handler
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
        elif state == "phase11":
            self.handle_phase11(vehicle, dt)
        elif state == "return_to_garage":
            self.handle_return_to_garage_phase(vehicle, dt)
        else:
            print(f"Unbekannter Zustand: {state}")
        return Task.cont

    # -------------------- Handler für einzelne Phasen --------------------

    def handle_translate_phase(self, vehicle, dt):
        # Wenn noch kein Auftrag zugeordnet wurde, wähle einen Auftrag aus.
        current_order = vehicle.getPythonTag("current_order")
        if current_order is None:
            next_order = self.select_next_order(vehicle)
            if next_order is not None:
                next_order["status"] = "In Bearbeitung"
                next_order["vehicle"] = f"Fahrzeug {vehicle.getPythonTag('vehicle_id')}"
                vehicle.setPythonTag("current_order", next_order)
                print(f"Auftrag {next_order['id']} wird zugewiesen für Fahrzeug {vehicle.getPythonTag('vehicle_id')}.")
            else:
                print("Kein Auftrag verfügbar – Fallback zum globalen Ziel.")
            current_order = vehicle.getPythonTag("current_order")

        # Bestimme das Ziel (Pickup-Station über den blauen Marker)
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

        # Berechne den tatsächlichen Steuerpunkt (also den Offset-Punkt)
        offset_pos = current_pos + vehicle.getQuat(self.render).xform(self.pickup_offset)

        # Berechne den gewünschten Heading-Winkel: Richtung von Offset-Punkt zum Ziel
        desired_heading_rad = math.atan2(target.getY() - offset_pos.getY(),
                                         target.getX() - offset_pos.getX())

        # Ermittle aktuellen Heading-Winkel über den `steering_axis`
        global_hpr = pivot.getNetTransform().getHpr()
        current_heading_rad = math.radians(global_hpr.getX())

        # Berechnung des Fehlerwinkels
        heading_error = desired_heading_rad - current_heading_rad
        while heading_error > math.pi:
            heading_error -= 2 * math.pi
        while heading_error < -math.pi:
            heading_error += 2 * math.pi

        # Drehung zur Korrektur, nur basierend auf Fehlerwinkel
        gain = 1.0
        max_delta = gain * dt
        delta_heading_rad = max(-max_delta, min(max_delta, heading_error))
        self.rotate_around_pivot(vehicle, pivot, math.degrees(delta_heading_rad))

        # Bewege das Fahrzeug entlang der neuen Richtung
        global_hpr = pivot.getNetTransform().getHpr()
        new_heading_rad = math.radians(global_hpr.getX())
        speed = 1.5
        new_x = current_pos.getX() + speed * math.cos(new_heading_rad) * dt
        new_y = current_pos.getY() + speed * math.sin(new_heading_rad) * dt
        new_pos = Vec3(new_x, new_y, 0)
        vehicle.setPos(new_pos)

        # Aktualisiere den Offset-Punkt (Steuerachse) nach der Bewegung
        new_offset_pos = vehicle.getPos(self.render) + vehicle.getQuat(self.render).xform(self.pickup_offset)

        # Prüfe, ob sich der Offset-Punkt exakt auf dem Ziel befindet
        if (target - new_offset_pos).length() < 0.1:
            vehicle.setPythonTag("order_state", "rotate")  # Wechsel zur nächsten Phase

    def handle_rotate_phase(self, vehicle, dt):
        import math
        from panda3d.core import Vec3

        # 1. Hole den grünen Referenzpunkt (fork_green) der Gabel.
        fork_green = vehicle.getPythonTag("fork_green")
        if not fork_green or fork_green.isEmpty():
            print("[DEBUG] handle_rotate_phase: Kein fork_green gefunden!")
            return

        # 2. Hole den aktuellen Auftrag und die zugehörige Pickup-Station.
        current_order = vehicle.getPythonTag("current_order")
        if not current_order or "pickup_station" not in current_order:
            print("[DEBUG] handle_rotate_phase: Kein aktueller Auftrag oder Station gefunden!")
            return
        station = current_order["pickup_station"]

        # Hole den Referenzpunkt der Station (white_center) und den Richtungsvektor (white_direction)
        white_center = station.getPythonTag("white_center")
        if white_center is None:
            print("[DEBUG] handle_rotate_phase: Kein white_center in der Station gefunden!")
            return
        target = white_center  # Ziel: Mittelpunkt der weißen Linie

        # 3. Berechne den Drehpunkt des Fahrzeugs.
        pivot = vehicle.getPos(self.render) + vehicle.getQuat(self.render).xform(self.pickup_offset)

        # 4. Falls sich der pivot nahe am Ziel befindet, final: Setze die exakte Ausrichtung.
        distance = (target - pivot).length()
        stop_threshold = 0.5  # Schwellenwert, evtl. an Modelldimensionen anpassen
        if distance < stop_threshold:
            desired_vector = target - pivot
            desired_angle = math.degrees(math.atan2(desired_vector.getY(), desired_vector.getX())) + 90
            desired_angle %= 360
            vehicle.setH(self.render, desired_angle)
            print(f"[DEBUG] final step: Fahrzeugheading auf {desired_angle:.2f}° gesetzt.")

            # Final: Richte den grünen Richtungspfeil ("fork_center_line") exakt aus.
            white_direction = station.getPythonTag("white_direction")
            if white_direction is not None:
                desired_arrow_angle = math.degrees(math.atan2(white_direction.getY(), white_direction.getX()))
                arrow_relative = (desired_arrow_angle - desired_angle + 180) % 360 - 180
                fork_center_line = vehicle.getPythonTag("fork_center_line")
                if fork_center_line:
                    fork_center_line.setH(arrow_relative)
                    print(f"[DEBUG] final step: Grüner Pfeil auf relativen Winkel {arrow_relative:.2f}° gesetzt.")
            # Hier ändern wir den Zustand in 'approach' statt "next_phase"
            vehicle.setPythonTag("order_state", "approach")
            return

        # 5. Andernfalls: Berechne den gewünschten globalen Winkel (inklusive +90°-Offset)
        desired_vector = target - pivot
        desired_angle = math.degrees(math.atan2(desired_vector.getY(), desired_vector.getX())) + 90
        desired_angle %= 360

        # 6. Ermittle den aktuellen Fahrzeugheading in Weltkoordinaten und berechne die Winkelabweichung.
        current_heading = vehicle.getH(self.render)
        angle_diff = (desired_angle - current_heading + 180) % 360 - 180

        if abs(angle_diff) < 2.0:
            vehicle.setH(self.render, desired_angle)
            white_direction = station.getPythonTag("white_direction")
            if white_direction is not None:
                desired_arrow_angle = math.degrees(math.atan2(white_direction.getY(), white_direction.getX()))
                arrow_relative = (desired_arrow_angle - desired_angle + 180) % 360 - 180
                fork_center_line = vehicle.getPythonTag("fork_center_line")
                if fork_center_line:
                    fork_center_line.setH(arrow_relative)
                    print(f"[DEBUG] fine alignment: Grüner Pfeil auf {arrow_relative:.2f}° gesetzt.")
            # Ändere auch hier sofort den Zustand in "approach"
            vehicle.setPythonTag("order_state", "approach")
            return

        # 7. Begrenze die Drehung pro Frame (z.B. 20,9° pro Sekunde)
        max_rotation_speed = 20.9  # Grad pro Sekunde
        max_delta = max_rotation_speed * dt
        delta_angle = max(-max_delta, min(max_delta, angle_diff))

        # 8. Drehe das Fahrzeug schrittweise um delta_angle
        temp_pivot = self.render.attachNewNode("temp_pivot")
        temp_pivot.setPos(pivot)
        self.rotate_around_pivot(vehicle, temp_pivot, delta_angle)
        temp_pivot.removeNode()

        print(f"[DEBUG] rotating: Gedreht um {delta_angle:.2f}°; Restliche Differenz: {angle_diff - delta_angle:.2f}°")

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
            vehicle.setPythonTag("order_state", "to_delivery")
            vehicle.setPythonTag("drive_out_target", None)

    def handle_to_delivery_phase(self, vehicle, dt):
        current_order = vehicle.getPythonTag("current_order")
        if current_order is None:
            return
        # Ziel der Abgabestation als Vektor verwenden:
        delivery_target_str = current_order.get("ziel", "Abgabestation 1")
        try:
            target_index = int(delivery_target_str.split()[-1])
        except ValueError:
            target_index = 1
        if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
            target = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
        else:
            target = self.abgabe_blue_dots[0].getPos(self.render)
        current_pos = vehicle.getPos(self.render)
        pivot = vehicle.getPythonTag("steering_axis")
        global_hpr = pivot.getNetTransform().getHpr()
        global_heading = global_hpr.getX()
        current_heading_rad = math.radians(global_heading)
        desired_heading_rad = math.atan2(target.getY() - current_pos.getY(),
                                         target.getX() - current_pos.getX())
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
        speed = 1.5
        new_x = current_pos.getX() + speed * math.cos(new_heading_rad) * dt
        new_y = current_pos.getY() + speed * math.sin(new_heading_rad) * dt
        new_pos = Vec3(new_x, new_y, 0)
        vehicle.setPos(new_pos)
        if math.sqrt((target.getX() - new_pos.getX()) ** 2 + (target.getY() - new_pos.getY()) ** 2) < 0.5:
            print(
                f"Phase 7 abgeschlossen: Fahrzeug {vehicle.getPythonTag('vehicle_id')} hat den blauen Punkt erreicht.")
            vehicle.setPythonTag("order_state", "align_delivery")

    def handle_align_delivery_phase(self, vehicle, dt):
        desired_heading = 90.0
        current_heading = vehicle.getH() % 360
        angle_diff = ((desired_heading - current_heading + 180) % 360) - 180
        print(
            f"Phase 8: Align Delivery | Fahrzeug {vehicle.getPythonTag('vehicle_id')}: Current {current_heading:.2f}°, Desired {desired_heading:.2f}°, Diff {angle_diff:.2f}°")
        fixed_turn_speed = 90.0
        turn_amount = fixed_turn_speed * dt
        if abs(angle_diff) < 1.0:
            vehicle.setH(desired_heading)
            print(
                f"Phase 8 abgeschlossen: Fahrzeug {vehicle.getPythonTag('vehicle_id')} ausgerichtet (Heading = {desired_heading:.2f}°).")
            vehicle.setPythonTag("order_state", "delivery_center")
        else:
            new_heading = current_heading + (turn_amount if angle_diff > 0 else -turn_amount)
            new_heading %= 360
            vehicle.setH(new_heading)
            print(f"Phase 8: Rotating - Fahrzeug {vehicle.getPythonTag('vehicle_id')} New Heading: {new_heading:.2f}°")

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
        current_order = vehicle.getPythonTag("current_order")
        if vehicle.getPythonTag("package_attached"):
            delivery_target_str = current_order.get("ziel", "Abgabestation 1")
            try:
                target_index = int(delivery_target_str.split()[-1])
            except ValueError:
                target_index = 1
            # (Bei Bedarf kann man hier noch Zielpositionen abfragen.)
            self.drop_cargo(vehicle)
            print(f"Phase 10: Paket abgesetzt für Fahrzeug {vehicle.getPythonTag('vehicle_id')}")
            vehicle.setPythonTag("package_attached", False)
        else:
            fork_node = vehicle.getPythonTag("fork_node")
            current_z = fork_node.getZ()
            if current_z > 0:
                lower_speed = 0.5
                new_z = max(0, current_z - lower_speed * dt)
                fork_node.setZ(new_z)
                print(
                    f"Phase 10: Gabel wird abgesenkt für Fahrzeug {vehicle.getPythonTag('vehicle_id')}, aktueller Z-Wert: {new_z}")
            else:
                print(f"Phase 10: Dropoff abgeschlossen für Fahrzeug {vehicle.getPythonTag('vehicle_id')}")
                if vehicle.getPythonTag("standby_pending"):
                    vehicle.setPythonTag("order_state", "return_to_garage")
                    print(f"Fahrzeug {vehicle.getPythonTag('vehicle_id')} kehrt zur Garage zurück (Standby).")
                else:
                    vehicle.setPythonTag("order_state", "translate")
                current_order["status"] = "Abgegeben"
                current_order["delivered_at"] = self.sim_clock
                vehicle.clearPythonTag("current_order")

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