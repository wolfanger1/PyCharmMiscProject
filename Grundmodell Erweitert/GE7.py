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

        # --- Aufbau der Umgebung ---
        # Ursprung und Kamera
        self.draw_origin()
        self.cam.setPos(11, -80, 40)
        self.cam.lookAt(11, 30, 0)

        # Licht und Raster
        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=70, cell_size=1)

        # Erzeuge Wände und Stations-Objekte (Annahme-, Abgabe-, und Garagenstationen)
        self.create_wall()
        self.create_annahme_stations()
        self.create_abgabe_stations()
        self.create_garagen_stations()

        # Für jede Annahmestation ein Paket spawnen
        for station in self.annahme_stations:
            self.spawn_package_at_station(station)

        # Fahrzeuge in den Garagen erstellen (insgesamt 5 Fahrzeuge)
        self.create_garage_vehicles()

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

        # Integration von TensorFlow: Modell laden
        # Beispiel: In __init__ der Klasse LagerSimulation, direkt nach dem Laden des TensorFlow Modells
        try:
            import tensorflow as tf
            self.tf_model = tf.keras.models.load_model("pfad/zum/saved_model")  # Passe den Pfad an
            print("TensorFlow Modell erfolgreich geladen.")
        except Exception as e:
            print(f"Fehler beim Laden des TensorFlow Modells: {e}")
            self.tf_model = None

        # Hier initialisieren wir die Trainingsdaten-Liste.
        self.training_data = []  # Tupel: (sensor_data, ideal_correction)

        # **** Neuer Code: Instanziere den RL-Agenten ****
        # Beispielparameter: state_bins definiert einen Zustandsraum für [Min-Abstand, aktuelle Geschwindigkeit]
        state_bins = ((10, 10), (10, 10))  # max_distance=10 in 10 Bins, max_speed=10 in 10 Bins
        action_space = [0, 1, 2]  # 0: keine zusätzliche Bremsung, 1: 20% Reduktion, 2: 50% Reduktion
        self.rl_agent = RLAgent(state_bins, action_space, learning_rate=0.1, discount_factor=0.9, epsilon=0.2)
        # **************************************************

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
    def draw_origin(self):
        ls = LineSegs()
        ls.setThickness(2)
        ls.setColor(LColor(1, 0, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(1, 0, 0)
        ls.setColor(LColor(0, 1, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 1, 0)
        ls.setColor(LColor(0, 0, 1, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, 1)
        self.render.attachNewNode(ls.create())

    def erzeuge_licht(self):
        alight = AmbientLight("ambient_light")
        alight.setColor((0.5, 0.5, 0.5, 1))
        alight_np = self.render.attachNewNode(alight)
        self.render.setLight(alight_np)
        dlight = DirectionalLight("directional_light")
        dlight.setColor((1, 1, 1, 1))
        dlight_np = self.render.attachNewNode(dlight)
        dlight_np.setPos(10, -10, 10)
        self.render.setLight(dlight_np)

    def erzeuge_bodenraster(self, center_extent=70, cell_size=1):
        vertex_format = GeomVertexFormat.getV3()
        vdata = GeomVertexData("grid", vertex_format, Geom.UHStatic)
        writer = GeomVertexWriter(vdata, "vertex")
        lines = GeomLines(Geom.UHStatic)
        n_vertices = 0
        min_line = -center_extent - 0.5
        max_line = center_extent + 0.5
        y = min_line
        while y <= max_line:
            writer.addData3f(min_line, y, 0)
            writer.addData3f(max_line, y, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            y += cell_size
        x = min_line
        while x <= max_line:
            writer.addData3f(x, min_line, 0)
            writer.addData3f(x, max_line, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            x += cell_size
        lines.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        np_grid = self.render.attachNewNode(node)
        np_grid.setColor(LColor(0.7, 0.7, 0.7, 1))
        return np_grid

    def create_wall(self):
        p1 = Vec3(0, 0, 0)
        p2 = Vec3(0, 60, 0)
        p3 = Vec3(22, 60, 0)
        p4 = Vec3(22, 0, 0)
        self.add_wall_segment(p1, p2)
        self.add_wall_segment(p2, p3)
        self.add_wall_segment(p3, p4)
        self.add_wall_segment(p4, p1)

    def add_wall_segment(self, start, end, height=2.0, thickness=0.5):
        seg_vector = end - start
        length = seg_vector.length()
        if length == 0:
            return
        d = seg_vector.normalized()
        outward = Vec3(-d.getY(), d.getX(), 0)
        center = (start + end) * 0.5 + outward * (thickness / 2.0)
        center.setZ(height / 2.0)
        angle = math.degrees(math.atan2(seg_vector.getY(), seg_vector.getX()))
        wall_np = self.render.attachNewNode("wall_np")
        wall = self.loader.loadModel("models/box")
        bounds = wall.getTightBounds()
        if bounds:
            low, high = bounds
            box_center = (low + high) * 0.5
            wall.setPos(-box_center)
        wall.reparentTo(wall_np)
        wall_np.setScale(length, thickness, height)
        wall_np.setPos(center)
        wall_np.setH(angle)
        wall_np.setTextureOff(1)
        wall_np.setColor(LColor(0.5, 0.5, 0.5, 1))

    def update_cable(self, task):
        # Verwende die simulative Zeit, die bereits in update_sim_clock hochgezählt wird
        t = self.sim_clock
        new_height = 0.5 + 0.5 * math.sin(t * 2.0)
        self.fork_node.setZ(new_height)
        return Task.cont

    # ---------------4. Erstellung der Stationen---------------
    def create_annahme_station(self, pos):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(0, 1, 0, 1))
        v0 = pos + Vec3(0, 0, 0)
        v1 = pos + Vec3(1, 0, 0)
        v2 = pos + Vec3(1, 1, 0)
        v3 = pos + Vec3(0, 1, 0)
        v4 = pos + Vec3(0, 0, 1)
        v5 = pos + Vec3(1, 0, 1)
        v6 = pos + Vec3(1, 1, 1)
        v7 = pos + Vec3(0, 1, 1)
        ls.moveTo(v0)
        ls.drawTo(v1)
        ls.moveTo(v2)
        ls.drawTo(v3)
        ls.moveTo(v3)
        ls.drawTo(v0)
        ls.moveTo(v4)
        ls.drawTo(v5)
        ls.moveTo(v6)
        ls.drawTo(v7)
        ls.moveTo(v7)
        ls.drawTo(v4)
        ls.moveTo(v0)
        ls.drawTo(v4)
        ls.moveTo(v3)
        ls.drawTo(v7)
        return self.render.attachNewNode(ls.create())

    def create_annahme_stations(self):
        """
        Erzeugt die Annahmestationen und erstellt für jede Station:
          - Einen weißen Marker zur Orientierung
          - Einen grünen Punkt (optional)
          - Eine weiße Linie, an deren Endpunkt ein blauer Marker als Ziel in der "Translate‑Phase" dient

        Zusätzlich wird ein Dictionary self.station_blue_dots aufgebaut, in dem jedem Annahmestations‑Node
        der zugehörige blaue Marker zugeordnet wird. Außerdem wird für die erste Station die globale Variable
        self.station_white_direction festgelegt.
        """
        station_points = [
            Vec3(0, 5, 0), Vec3(0, 10, 0), Vec3(0, 15, 0),
            Vec3(0, 20, 0), Vec3(0, 25, 0), Vec3(0, 30, 0),
            Vec3(0, 35, 0), Vec3(0, 40, 0), Vec3(0, 45, 0),
            Vec3(0, 50, 0)
        ]
        self.annahme_stations = []
        self.station_blue_dots = {}

        for i, pt in enumerate(station_points, start=1):
            # Erstelle die Basisstation (zum Beispiel als Rahmen)
            self.create_annahme_station(pt)
            station_dummy = self.render.attachNewNode(f"annahme_station_{i}")
            station_dummy.setPos(pt)
            self.annahme_stations.append(station_dummy)

            # Berechne den Mittelpunkt der Station
            center = pt + Vec3(0.5, 0.5, 0.5)

            # Erzeuge den weißen Marker als Orientierung
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            # Erzeuge den grünen Punkt (optional)
            green_dot = self.loader.loadModel("models/misc/sphere")
            green_dot.setScale(0.1)
            green_dot.setColor(LColor(0, 1, 0, 1))
            green_dot.setPos(center + Vec3(0, 0, -0.5))
            green_dot.reparentTo(self.render)

            # Zeichne die weiße Linie: Sie beginnt bei center + Vec3(0, 0, -0.5) und verläuft 3 Meter in X‑Richtung.
            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())
            # Beispiel in create_annahme_stations – nach dem Zeichnen der weißen Linie:
            station_dummy.setPythonTag("white_center", (start_line + end_line) * 0.5)
            line_vec = end_line - start_line
            if line_vec.length() != 0:
                station_dummy.setPythonTag("white_direction", Vec2(line_vec.getX(), line_vec.getY()).normalized())
            else:
                station_dummy.setPythonTag("white_direction", Vec2(1, 0))

            # Erzeuge den blauen Marker, der als Ziel in der Translate‑Phase dient
            blue_dot = self.loader.loadModel("models/misc/sphere")
            blue_dot.setScale(0.1)
            blue_dot.setColor(LColor(0, 0, 1, 1))
            blue_dot.setPos(end_line)
            blue_dot.reparentTo(self.render)

            # Speichere den blauen Marker im Dictionary, sodass er später erzeugt werden kann
            self.station_blue_dots[station_dummy] = blue_dot

            # Optionale Textanzeige der Stationsnummer
            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 1.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

            # Zusätzliche Markierungen (Kreuze) – falls benötigt:
            v0 = pt + Vec3(0, 0, 0)
            v1 = pt + Vec3(1, 0, 0)
            v2 = pt + Vec3(1, 1, 0)
            v3 = pt + Vec3(0, 1, 0)
            v4 = pt + Vec3(0, 0, 1)
            v5 = pt + Vec3(1, 0, 1)
            v6 = pt + Vec3(1, 1, 1)
            v7 = pt + Vec3(0, 1, 1)
            self.add_cross_on_face([v0, v3, v7, v4], color=LColor(0, 1, 0, 1))
            self.add_cross_on_face([v0, v1, v5, v4], color=LColor(0, 1, 0, 1))
            self.add_cross_on_face([v3, v2, v6, v7], color=LColor(0, 1, 0, 1))

            # Für die erste Station (oder den ersten relevanten Pickup) setzen wir globale Referenzen,
            # die in vehicle_order_task benötigt werden.
            if i == 1:
                self.blue_dot = blue_dot
                self.station_green_dot = green_dot
                # Berechne den Mittelpunkt der weißen Linie als Referenz (optional)
                self.white_line_center = (start_line + end_line) * 0.5
                line_vec = end_line - start_line
                if line_vec.length() != 0:
                    self.station_white_direction = Vec2(line_vec.getX(), line_vec.getY()).normalized()
                else:
                    self.station_white_direction = Vec2(1, 0)  # Fallback-Wert

    def create_abgabe_station(self, pos):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(1, 0, 0, 1))
        v0 = pos + Vec3(0, 0, 0)
        v1 = pos + Vec3(1, 0, 0)
        v2 = pos + Vec3(1, 1, 0)
        v3 = pos + Vec3(0, 1, 0)
        v4 = pos + Vec3(0, 0, 1)
        v5 = pos + Vec3(1, 0, 1)
        v6 = pos + Vec3(1, 1, 1)
        v7 = pos + Vec3(0, 1, 1)
        ls.moveTo(v0)
        ls.drawTo(v1)
        ls.moveTo(v1)
        ls.drawTo(v2)
        ls.moveTo(v2)
        ls.drawTo(v3)
        ls.moveTo(v4)
        ls.drawTo(v5)
        ls.moveTo(v5)
        ls.drawTo(v6)
        ls.moveTo(v6)
        ls.drawTo(v7)
        ls.moveTo(v1)
        ls.drawTo(v5)
        ls.moveTo(v2)
        ls.drawTo(v6)
        return self.render.attachNewNode(ls.create())

    def create_abgabe_stations(self):
        station_points = [
            Vec3(21, 5, 0), Vec3(21, 10, 0), Vec3(21, 15, 0),
            Vec3(21, 20, 0), Vec3(21, 25, 0), Vec3(21, 30, 0),
            Vec3(21, 35, 0), Vec3(21, 40, 0), Vec3(21, 45, 0),
            Vec3(21, 50, 0)
        ]
        self.abgabe_stations = []  # Liste der Abgabestationen
        self.abgabe_blue_dots = []  # Liste zum Speichern der blauen Marker für die Abgabe

        for i, pt in enumerate(station_points, start=1):
            # Erstelle die Basiskonstruktion der Abgabestation
            node = self.create_abgabe_station(pt)
            self.abgabe_stations.append(node)

            # Berechne den Mittelpunkt der Station
            center = pt + Vec3(0.5, 0.5, 0.5)

            # Marker am Zentrum (weiß)
            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            # Grüner Punkt: center + Vec3(0, 0, -0.5)
            green_dot = self.loader.loadModel("models/misc/sphere")
            green_dot.setScale(0.1)
            green_dot.setColor(LColor(0, 1, 0, 1))
            green_dot.setPos(center + Vec3(0, 0, -0.5))
            green_dot.reparentTo(self.render)

            # Weiße Linie: Startet bei center + Vec3(0, 0, -0.5)
            # und verläuft 3 Meter in negativer X-Richtung
            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(-3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())

            # Blauer Punkt: wird an der Endposition der Linie erzeugt
            blue_dot = self.loader.loadModel("models/misc/sphere")
            blue_dot.setScale(0.1)
            blue_dot.setColor(LColor(0, 0, 1, 1))
            blue_dot.setPos(end_line)
            blue_dot.reparentTo(self.render)
            # Speichere den blauen Marker für spätere Navigation der Abgabestation
            self.abgabe_blue_dots.append(blue_dot)

            # Anzeige der Stationsnummer (textuell)
            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x - 0.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

            # Zusätzliche Markierungen (Kreuze) auf der Station
            v0 = pt + Vec3(0, 0, 0)
            v1 = pt + Vec3(1, 0, 0)
            v2 = pt + Vec3(1, 1, 0)
            v3 = pt + Vec3(0, 1, 0)
            v4 = pt + Vec3(0, 0, 1)
            v5 = pt + Vec3(1, 0, 1)
            v6 = pt + Vec3(1, 1, 1)
            v7 = pt + Vec3(0, 1, 1)
            self.add_cross_on_face([v1, v2, v6, v5], color=LColor(1, 0, 0, 1))
            self.add_cross_on_face([v0, v1, v5, v4], color=LColor(1, 0, 0, 1))
            self.add_cross_on_face([v3, v2, v6, v7], color=LColor(1, 0, 0, 1))

    def create_garage_station(self, pos):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(0, 0, 1, 1))
        v0 = pos + Vec3(0, 0, 0)
        v1 = pos + Vec3(1, 0, 0)
        v2 = pos + Vec3(1, 2, 0)
        v3 = pos + Vec3(0, 2, 0)
        v4 = pos + Vec3(0, 0, 3)
        v5 = pos + Vec3(1, 0, 3)
        v6 = pos + Vec3(1, 2, 3)
        v7 = pos + Vec3(0, 2, 3)
        edges = [
            (v0, v1), (v1, v2), (v2, v3), (v3, v0),
            (v4, v5), (v5, v6), (v6, v7), (v7, v4),
            (v0, v4), (v1, v5), (v2, v6), (v3, v7)
        ]
        for p, q in edges:
            if p.getY() == pos.getY() and q.getY() == pos.getY():
                continue
            ls.moveTo(p)
            ls.drawTo(q)
        node = self.render.attachNewNode(ls.create())
        self.add_cross_on_face([v3, v2, v6, v7], color=LColor(0, 0, 1, 1))
        self.add_cross_on_face([v0, v3, v7, v4], color=LColor(0, 0, 1, 1))
        self.add_cross_on_face([v1, v2, v6, v5], color=LColor(0, 0, 1, 1))
        return node

    def add_garage_roof(self, pos):
        cm = CardMaker("garage_roof")
        cm.setFrame(0, 1, 0, 2)
        roof = self.render.attachNewNode(cm.generate())
        roof.setHpr(0, -90, 0)
        roof.setPos(pos.x, pos.y, pos.z + 3)
        roof.setColor(LColor(0, 0, 1, 1))
        return roof

    def create_garagen_stations(self):
        station_points = [
            Vec3(3, 58, 0), Vec3(7, 58, 0), Vec3(11, 58, 0),
            Vec3(15, 58, 0), Vec3(19, 58, 0)
        ]
        self.garagen_stations = []
        self.garagen_parking_points = []
        for i, pt in enumerate(station_points, start=1):
            self.create_garage_station(pt)
            self.add_garage_roof(pt)
            self.garagen_stations.append(pt)
            # ParkpunktGarage: Verschoben um 0.5 in negativer Y-Richtung:
            center = pt + Vec3(0.5, 0.5, 1.5)
            ParkpunktGarage = center + Vec3(0, 0, 0.7)
            self.garagen_parking_points.append(ParkpunktGarage)
            tn = TextNode("garage_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 0.5, pt.y - 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

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

    def add_cross_on_face(self, corners, color=LColor(1, 1, 1, 1), thickness=1.5):
        """
        Zeichnet ein Kreuz (zwei diagonale Linien) auf der Fläche,
        definiert durch die vier Ecken in 'corners'.

        Parameters:
          corners (list of Vec3): Liste aus vier Eckpunkten der Fläche.
          color (LColor): Farbe des Kreuzes.
          thickness (float): Linienstärke.

        Returns:
          NodePath: Das NodePath-Objekt, welches die gezeichneten Linien beinhaltet.
        """
        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(corners[0])
        ls.drawTo(corners[2])
        ls.moveTo(corners[1])
        ls.drawTo(corners[3])
        return self.render.attachNewNode(ls.create())

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
        dt = ClockObject.getGlobalClock().getDt() * self.speed_factor

        # Frame-Zähler einbauen, um die Frequenz der Modellinferenz zu reduzieren
        frame_count = vehicle.getPythonTag("frame_count")
        if frame_count is None:
            frame_count = 0
        frame_count += 1
        vehicle.setPythonTag("frame_count", frame_count)

        # Sensordatenerfassung
        sensor_data = self.collect_sensor_data(vehicle)
        import numpy as np
        # Führe die Modellinferenz nur alle 10 Frames durch, um den Hauptthread zu entlasten
        if self.tf_model is not None and (frame_count % 10 == 0):
            input_data = sensor_data.reshape(1, sensor_data.shape[0], sensor_data.shape[1], 1)
            prediction = self.tf_model.predict(input_data)
            model_delta_angle = prediction[0][0]
            print(f"[TF] Modell-Korrektur: {model_delta_angle:.2f}°")
        else:
            model_delta_angle = 0.0
            if self.tf_model is not None:
                # Optional: Übersichtliche Ausgabe, wenn der Inferenzaufruf übersprungen wird
                print(f"[TF] Modell-Korrektur übersprungen (Frame Count: {frame_count})")
            else:
                print("[TF] Kein Modell vorhanden, Modell-Korrektur wird übersprungen.")

        # Berechne den idealen Korrekturwert (unverändert)
        ideal_correction = self.compute_ideal_steering_correction(vehicle)
        print(f"[IDEAL] Ideal berechneter Korrekturwinkel: {ideal_correction:.2f}°")

        # Logge Trainingsdaten nur in der 'translate'-Phase
        state = vehicle.getPythonTag("order_state")
        if state == "translate":
            self.log_training_sample(sensor_data, ideal_correction)

        # Führe die zustandsabhängige Logik aus
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
        # --- Zusätzlicher Safety-Zweig in der Translate-Phase ---
        # (1) Zuerst: Falls ein Fahrzeug auf das Ziel (Pickup-Station) wartet, soll gewartet werden.
        current_order = vehicle.getPythonTag("current_order")
        station_occupied = False
        if current_order is not None and "pickup_station" in current_order:
            pickup_station = current_order["pickup_station"]
            if self.is_station_occupied(pickup_station, exclude_vehicle=vehicle):
                station_occupied = True
                print(
                    f"[WARTEN] Station {pickup_station.getName()} belegt. Fahrzeug {vehicle.getPythonTag('vehicle_id')} wartet.")

        # (2) Festlegen der Basisgeschwindigkeit:
        base_speed = 1.5 if not station_occupied else 0.0

        # (3) Kollisionsvermeidung: Passe die Geschwindigkeit an, wenn andere Fahrzeuge in der Nähe sind.
        adjusted_speed = self.collision_avoidance_adjustment(vehicle, base_speed)

        # --- Rest der originalen Translate-Logik ---
        # Falls kein Auftrag zugeordnet, versuche einen neuen Auftrag zu wählen.
        if current_order is None:
            next_order = self.select_next_order(vehicle)
            if next_order is not None:
                next_order["status"] = "In Bearbeitung"
                next_order["vehicle"] = f"Fahrzeug {vehicle.getPythonTag('vehicle_id')}"
                vehicle.setPythonTag("current_order", next_order)
                print(f"Auftrag {next_order['id']} wird zugewiesen für Fahrzeug {vehicle.getPythonTag('vehicle_id')}.")
            current_order = vehicle.getPythonTag("current_order")

        # Bestimme das Ziel: Zum Beispiel den blauen Marker der Pickup-Station.
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

        # Berechne den Offset-Punkt, von dem aus das Fahrzeug navigiert.
        offset_pos = current_pos + vehicle.getQuat(self.render).xform(self.pickup_offset)
        import math
        desired_heading_rad = math.atan2(target.getY() - offset_pos.getY(),
                                         target.getX() - offset_pos.getX())
        global_hpr = pivot.getNetTransform().getHpr()
        current_heading_rad = math.radians(global_hpr.getX())
        heading_error = desired_heading_rad - current_heading_rad
        while heading_error > math.pi:
            heading_error -= 2 * math.pi
        while heading_error < -math.pi:
            heading_error += 2 * math.pi

        # Berechne den Drehwinkel (gilt für die Korrektur) – normale Drehung.
        gain = 1.0
        max_delta = gain * dt
        delta_heading_rad = max(-max_delta, min(max_delta, heading_error))
        self.rotate_around_pivot(vehicle, pivot, math.degrees(delta_heading_rad))

        # Jetzt Vorwärtsbewegung: Verwende dafür die angepasste Geschwindigkeit.
        global_hpr = pivot.getNetTransform().getHpr()
        new_heading_rad = math.radians(global_hpr.getX())
        new_x = current_pos.getX() + adjusted_speed * math.cos(new_heading_rad) * dt
        new_y = current_pos.getY() + adjusted_speed * math.sin(new_heading_rad) * dt
        new_pos = Vec3(new_x, new_y, 0)
        vehicle.setPos(new_pos)

        # Wenn das Fahrzeug nahe genug am Ziel ist, wechsle den Zustand in die Rotationsphase.
        new_offset_pos = vehicle.getPos(self.render) + vehicle.getQuat(self.render).xform(self.pickup_offset)
        if (target - new_offset_pos).length() < 0.1:
            vehicle.setPythonTag("order_state", "rotate")

        return Task.cont

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
            return Task.cont

        # Bestimme den Zielpunkt der Abgabestation:
        delivery_target_str = current_order.get("ziel", "Abgabestation 1")
        try:
            target_index = int(delivery_target_str.split()[-1])
        except ValueError:
            target_index = 1
        if 0 <= target_index - 1 < len(self.abgabe_blue_dots):
            target = self.abgabe_blue_dots[target_index - 1].getPos(self.render)
        else:
            target = self.abgabe_blue_dots[0].getPos(self.render)

        # Prüfe, ob die Abgabestation bereits durch ein anderes Fahrzeug besetzt ist:
        if self.is_delivery_station_occupied(target, exclude_vehicle=vehicle, occupancy_threshold=1.0):
            print(f"[WARTEN] Abgabestation belegt. Fahrzeug {vehicle.getPythonTag('vehicle_id')} wartet.")
            return Task.cont  # Fahrzeug setzt keine Bewegung fort

        # Weiterhin: Standardlogik zur Bewegung Richtung Ziel:
        current_pos = vehicle.getPos(self.render)
        pivot = vehicle.getPythonTag("steering_axis")
        import math
        desired_heading_rad = math.atan2(target.getY() - current_pos.getY(),
                                         target.getX() - current_pos.getX())
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

        # Vorwärtsbewegung:
        new_heading_rad = math.radians(pivot.getNetTransform().getHpr().getX())
        speed = 1.5  # Basisgeschwindigkeit
        # Setze hier ggf. auch collision_avoidance_adjustment ein (wie in der translate-Phase)
        new_x = current_pos.getX() + speed * math.cos(new_heading_rad) * dt
        new_y = current_pos.getY() + speed * math.sin(new_heading_rad) * dt
        new_pos = Vec3(new_x, new_y, 0)
        vehicle.setPos(new_pos)

        # Falls die Position nahe dem Ziel liegt, wechsle den Zustand zur nächsten Phase:
        if (target - new_pos).length() < 0.5:
            print(f"Fahrzeug {vehicle.getPythonTag('vehicle_id')} hat die Abgabestation erreicht.")
            vehicle.setPythonTag("order_state", "align_delivery")

        return Task.cont

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
        current_pos = current_vehicle.getPos(self.render)
        adjusted_speed = base_speed
        # Berechne einen Basisfaktor (z.B. basierend auf Abstand zu anderen Fahrzeugen):
        for veh in self.garage_vehicles:
            if veh == current_vehicle:
                continue
            other_pos = veh.getPos(self.render)
            distance = (current_pos - other_pos).length()
            if distance < safe_distance:
                factor = (distance / safe_distance) ** 2
                candidate_speed = base_speed * factor
                if candidate_speed < adjusted_speed:
                    adjusted_speed = candidate_speed

        # Hier integrieren wir den RL-Ausdruck:
        # Nehme als Zustandsvektor bspw. [min_distance_to_others, current_speed]
        min_distance = min(
            [(current_pos - v.getPos(self.render)).length() for v in self.garage_vehicles if v != current_vehicle])
        current_speed = self.current_speed  # oder eine entsprechende Eigenschaft des Fahrzeugs
        state = [min_distance, current_speed]

        # Angenommen, du hast für jedes Fahrzeug einen eigenen RL-Agenten (oder einen globalen)
        action = self.rl_agent.select_action(state)
        # Definiere, wie Aktion in einen zusätzlichen Bremsfaktor übersetzt wird:
        # Beispiel: Aktion 0: kein zusätzlicher Bremsfaktor, 1: 20% Reduktion, 2: 50% Reduktion
        action_to_factor = {0: 1.0, 1: 0.8, 2: 0.5}
        braking_factor = action_to_factor.get(action, 1.0)
        adjusted_speed *= braking_factor

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
        Prüft, ob sich ein Fahrzeug in der Nähe der Abgabestation (target_pos) befindet.
        ignore 'exclude_vehicle', falls dieses nicht berücksichtigt werden soll.
        """
        for veh in self.garage_vehicles:
            if veh == exclude_vehicle:
                continue
            if (veh.getPos(self.render) - target_pos).length() < occupancy_threshold:
                return True

        return False

    def check_collisions(self):
        collision_threshold = 1.0  # z. B. wenn Fahrzeuge näher als 1 Einheit sind
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
        collisions = self.check_collisions()
        for veh1, veh2 in collisions:
            # Für jedes beteiligte Fahrzeug:
            for veh in (veh1, veh2):
                # Erstelle einen Zustandsvektor – analog zum, der in collision_avoidance_adjustment verwendet wird.
                current_pos = veh.getPos(self.render)
                min_distance = min([(current_pos - v.getPos(self.render)).length()
                                    for v in self.garage_vehicles if v != veh])
                current_speed = self.current_speed  # oder fahrzeugspezifisch
                state = [min_distance, current_speed]
                # Nehme an, die letzte von deinem Agenten gewählte Aktion ist gespeichert (das könntest du in einem PythonTag ablegen)
                last_action = veh.getPythonTag("last_braking_action")

                # Definiere den negativen Reward
                reward = -10
                # Erfasse den nächsten Zustand (nach Entfernen des Kollisionsereignisses oder nach einer kurzen Verzögerung)
                next_state = state  # In einem echten Setup wäre hier der nächste gemessene Zustand
                self.rl_agent.update(state, last_action, reward, next_state)
                print(f"RL-Update für Fahrzeug {veh.getPythonTag('vehicle_id')}: Kollisionsreward {reward} vergeben.")

import random
import numpy as np

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