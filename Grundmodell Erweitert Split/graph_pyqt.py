import sys, time
from multiprocessing import Queue
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg

class GraphWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Echtzeit-Visualisierung")

        # Erstelle das Hauptlayout als vertikale Box
        main_layout = QtWidgets.QVBoxLayout(self)

        # --- Standard-Kennzahlen-Plots (3 Graphen) ---
        self.standard_group = QtWidgets.QGroupBox("Standard-Kennzahlen")
        standard_layout = QtWidgets.QVBoxLayout(self.standard_group)

        self.plot1 = pg.PlotWidget(title="Abgegebene Pakete pro Minute")
        self.plot2 = pg.PlotWidget(title="Durchschnittliche Liegedauer (s)")
        self.plot3 = pg.PlotWidget(title="Durchschnittliche Lieferzeit (s)")

        # Setze den Hintergrund auf weiß
        self.plot1.setBackground('w')
        self.plot2.setBackground('w')
        self.plot3.setBackground('w')

        standard_layout.addWidget(self.plot1)
        standard_layout.addWidget(self.plot2)
        standard_layout.addWidget(self.plot3)
        # Sicherstellen, dass die Gruppe expandiert
        self.standard_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        main_layout.addWidget(self.standard_group, 1)  # gleicher Stretch-Faktor

        # Erstelle die Kurven für die Standarddaten
        self.curve1 = self.plot1.plot(pen='y', symbol='o')
        self.curve2 = self.plot2.plot(pen='r', symbol='o')
        self.curve3 = self.plot3.plot(pen='g', symbol='o')

        # --- Fahrzeugratings in separaten Tabs ---
        self.vehicle_group = QtWidgets.QGroupBox("Fahrzeugbewertungen")
        vehicle_layout = QtWidgets.QVBoxLayout(self.vehicle_group)

        self.tab_widget = QtWidgets.QTabWidget()
        # Stelle sicher, dass das Tab-Widget expandiert
        self.tab_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        vehicle_layout.addWidget(self.tab_widget)
        self.vehicle_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        main_layout.addWidget(self.vehicle_group, 1)  # gleicher Stretch-Faktor

        # Dictionary zum Speichern der Bewertung-Daten pro Fahrzeug.
        # Key: vehicle_id, Value: dict mit 'data' -> Liste (time, rating) und 'curve' -> Plot-Kurve.
        self.vehicle_plots = {}

        # Listen für die Standarddaten
        self.data = []  # Elemente: (time, ppm, dwell, delivery)

        # Timer für die Aktualisierung aller Graphen (500 ms)
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(500)

    def update_plots(self):
        # Aktualisiere die Standardplots
        if self.data:
            times = [d[0] for d in self.data]
            ppm = [d[1] for d in self.data]
            dwell = [d[2] for d in self.data]
            delivery = [d[3] for d in self.data]
            self.curve1.setData(times, ppm)
            self.curve2.setData(times, dwell)
            self.curve3.setData(times, delivery)
        # Aktualisiere alle Fahrzeug-Rating-Plots
        for vehicle_id, info in self.vehicle_plots.items():
            data = info['data']
            if data:
                times = [d[0] for d in data]
                ratings = [d[1] for d in data]
                info['curve'].setData(times, ratings)

    def add_standard_data(self, new_data):
        """
        Fügt Standarddaten im Format (time, ppm, dwell, delivery) hinzu.
        """
        self.data.append(new_data)

    def add_vehicle_rating_data(self, vehicle_id, new_data):
        """
        Fügt für das Fahrzeug vehicle_id Bewertungsdaten hinzu.
        new_data sollte ein Tupel (time, rating) sein.
        Falls für dieses Fahrzeug noch kein Plot existiert, wird ein neuer Tab angelegt.
        """
        if vehicle_id not in self.vehicle_plots:
            plot_widget = pg.PlotWidget(title=f"Fahrzeug {vehicle_id} Bewertung")
            plot_widget.setBackground('w')
            # Stelle sicher, dass auch dieser Plot expandiert
            plot_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            curve = plot_widget.plot(pen='y', symbol='o')
            self.vehicle_plots[vehicle_id] = {'data': [], 'curve': curve}
            self.tab_widget.addTab(plot_widget, f"Fahrzeug {vehicle_id}")
        self.vehicle_plots[vehicle_id]['data'].append(new_data)


def graph_process_pyqt(graph_queue: Queue):
    app = QtWidgets.QApplication(sys.argv)
    window = GraphWindow()
    window.show()

    def check_queue():
    timer = QtCore.QTimer()
    timer.setInterval(100)  # alle 100 ms
    timer.timeout.connect(check_queue)
    timer.start()

    sys.exit(app.exec_())


if __name__ == "__main__":
    from multiprocessing import Queue
    q = Queue()

    # Test: Sende zufällig generierte Standarddaten und Fahrzeugratings
    import random, time
    current_time = 0.0
    for i in range(50):
        # Standarddaten: (time, ppm, dwell, delivery)
        standard_data = (current_time,
                         random.uniform(0, 10),
                         random.uniform(0, 5),
                         random.uniform(0, 5))
        q.put(standard_data)
        # Fahrzeugratings für Fahrzeuge 1 bis 5: ("rating", vehicle_id, time, rating_value)
        for vid in range(1, 6):
            # Hier als Test: falls keine Kollision—+10, andernfalls zufällig zwischen -10 und -20
            rating = random.choice([10, -10, -15, -20])
            q.put(("rating", vid, current_time, rating))
        current_time += 1
        time.sleep(0.1)
#TEST
    graph_process_pyqt(q)
