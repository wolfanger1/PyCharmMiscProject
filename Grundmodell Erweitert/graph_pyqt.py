# graph_pyqt.py
import sys, time
from multiprocessing import Queue
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg


class GraphWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Echtzeit-Visualisierung")
        layout = QtWidgets.QVBoxLayout(self)

        # Erstelle drei Plot-Widgets für die Kennzahlen:
        self.plot1 = pg.PlotWidget(title="Abgegebene Pakete pro Minute")
        self.plot2 = pg.PlotWidget(title="Durchschnittliche Liegedauer (s)")
        self.plot3 = pg.PlotWidget(title="Durchschnittliche Lieferzeit (s)")

        # Setze den Hintergrund weiß:
        self.plot1.setBackground('w')
        self.plot2.setBackground('w')
        self.plot3.setBackground('w')

        layout.addWidget(self.plot1)
        layout.addWidget(self.plot2)
        layout.addWidget(self.plot3)

        # Erstelle Kurven (mit Symbolen):
        self.curve1 = self.plot1.plot(pen='y', symbol='o')
        self.curve2 = self.plot2.plot(pen='r', symbol='o')
        self.curve3 = self.plot3.plot(pen='g', symbol='o')

        self.data = []
        # Ein Timer, der die Daten alle 500 ms aktualisiert:
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(500)

    def update_plots(self):
        if not self.data:
            return
        times = [d[0] for d in self.data]
        ppm = [d[1] for d in self.data]
        dwell = [d[2] for d in self.data]
        delivery = [d[3] for d in self.data]
        self.curve1.setData(times, ppm)
        self.curve2.setData(times, dwell)
        self.curve3.setData(times, delivery)

    def add_data(self, new_data):
        self.data.append(new_data)


def graph_process_pyqt(graph_queue: Queue):
    # Erstelle die QApplication – das geschieht in diesem separaten Prozess
    app = QtWidgets.QApplication(sys.argv)
    window = GraphWindow()
    window.show()

    def check_queue():
        # Versuche, alle neuen Daten aus der Queue auszulesen
        while True:
            try:
                new_data = graph_queue.get_nowait()
                # Zum Debuggen:
                print("Empfangen:", new_data)
                window.add_data(new_data)
            except:
                break

    timer = QtCore.QTimer()
    timer.setInterval(100)  # alle 100 ms
    timer.timeout.connect(check_queue)
    timer.start()

    sys.exit(app.exec_())


if __name__ == "__main__":
    # Minimaler Test
    from multiprocessing import Queue

    q = Queue()
    graph_process_pyqt(q)
