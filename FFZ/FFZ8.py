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
    CardMaker,
    LineSegs,
    Vec3
)
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from direct.gui.DirectGui import DirectSlider, DirectLabel
import math


class SimpleSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Initialwerte für Simulationszeit und -geschwindigkeit
        self.sim_clock = 0.0
        self.speed_factor = 1.0

        # Kameraeinstellungen (Fahrtrichtung wird entlang der Y-Achse angenommen)
        self.cam.setPos(0, -30, 10)
        self.cam.lookAt(0, 0, 0)

        # Licht und Raster
        self.setup_light()
        self.create_grid(center_extent=10, cell_size=0.1)

        # Fahrzeug erstellen und Referenz speichern
        self.vehicle = self.create_vehicle()

        # Slider zur Anpassung der Simulationsgeschwindigkeit
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

        # Slider zur Steuerung der Forkhöhe (0 bis 1 Meter)
        self.fork_slider = DirectSlider(
            range=(0.0, 1.0),
            value=0.0,
            pageSize=0.01,
            command=self.update_fork_height,
            pos=(-0.7, 0, -0.85),
            scale=0.3
        )
        self.fork_label = DirectLabel(
            text="Fork Höhe: 0.00m",
            pos=(-0.7, 0, -0.75),
            scale=0.07
        )

        # Anzeige der Laufzeit
        self.info_label = DirectLabel(
            text="Laufzeit: 0.0s",
            pos=(1.2, 0, 0.8),
            scale=0.07,
            frameColor=(0, 0, 0, 0)
        )

        # Zoom-Funktionalität
        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

        # Aufgaben hinzufügen
        self.taskMgr.add(self.update_sim_clock, "UpdateSimClockTask")
        self.taskMgr.add(self.update_info_display, "UpdateInfoDisplayTask")
        self.taskMgr.add(self.update_cable, "UpdateCableTask")
        # Das Fahrzeug fährt stationär; update_vehicle Task wird nicht hinzugefügt.

    def update_sim_clock(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.sim_clock += dt * self.speed_factor
        return Task.cont

    def update_info_display(self, task):
        total_seconds = self.sim_clock
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        formatted_time = f"{hours}h {minutes}m {seconds:.1f}s"
        self.info_label['text'] = f"Laufzeit: {formatted_time}"
        return Task.cont

    def update_simulation_speed(self, speed_factor=None):
        if speed_factor is None:
            speed_factor = self.speed_slider['value']
        else:
            speed_factor = float(speed_factor)
        self.speed_factor = speed_factor
        self.speed_label['text'] = f"Sim Time Factor: {self.speed_factor:.1f}"

    def update_fork_height(self, height=0, *args):
        try:
            height = float(height)
        except ValueError:
            height = 0.0
        self.fork_node.setZ(height)
        self.fork_label['text'] = f"Fork Höhe: {height:.2f}m"

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

    def create_grid(self, center_extent=40, cell_size=1):
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
            lines.closePrimitive()
            n_vertices += 2
            y += cell_size

        x = min_line
        while x <= max_line:
            writer.addData3f(x, min_line, 0)
            writer.addData3f(x, max_line, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            lines.closePrimitive()
            n_vertices += 2
            x += cell_size

        geom = Geom(vdata)
        geom.addPrimitive(lines)
        node = GeomNode("grid")
        node.addGeom(geom)
        grid_np = self.render.attachNewNode(node)
        grid_np.setColor(0.7, 0.7, 0.7, 1)
        return grid_np

    def setup_light(self):
        ambient_light = AmbientLight("ambient_light")
        ambient_light.setColor((0.5, 0.5, 0.5, 1))
        ambient_np = self.render.attachNewNode(ambient_light)
        self.render.setLight(ambient_np)

        directional_light = DirectionalLight("directional_light")
        directional_light.setColor((1, 1, 1, 1))
        directional_np = self.render.attachNewNode(directional_light)
        directional_np.setPos(10, -10, 10)
        self.render.setLight(directional_np)

    def create_vehicle(self):
        vehicle_node = self.render.attachNewNode("vehicle")

        # Fahrmodul (Chassis) – Farbe: Rot, Dimensionen: 1 x 0.5 x 1.2
        box_chassis = self.create_box(1, 0.5, 1.2, (1.0, 0.0, 0.0, 1))
        node_chassis = vehicle_node.attachNewNode(box_chassis)
        node_chassis.setTwoSided(True)
        node_chassis.setPos(0, 0, 0)

        # Gabelmodul (Fork) – Statt eines massiven Blocks wird ein Elternknoten erstellt,
        # unter dem zwei "Zähne" angeordnet werden.
        fork_node = vehicle_node.attachNewNode("fork")
        # Positioniere den Fork-Knoten so, dass die freie Seite (global y = -1.2) genutzt wird.
        fork_node.setPos(0, -1.2, 0)

        # Linker Zahn (Zahn links vom Fork): Größe 0.2 x 1.2 x 0.1 (X, Y, Z)
        left_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_left = fork_node.attachNewNode(left_tooth)
        node_left.setTwoSided(True)
        node_left.setPos(0, 0, 0)  # von X=0 bis X=0.2

        # Rechter Zahn: Größe 0.2 x 1.2 x 0.1
        right_tooth = self.create_box(0.2, 1.2, 0.1, (0.3, 0.3, 0.3, 1))
        node_right = fork_node.attachNewNode(right_tooth)
        node_right.setTwoSided(True)
        node_right.setPos(0.8, 0, 0)  # von X=0.8 bis X=1.0

        # Speichere den Fork-Knoten für spätere Höhenanpassungen
        self.fork_node = fork_node

        # Mast – nicht mehr als massiver Block, sondern als Rahmen (nur Kanten in X und Z)
        # Wir bauen einen Rahmen mit außen: 1x1, Rahmenstärke (Border)=0.1, extrudiert in Y (Tiefe = 0.1)
        mast_node = vehicle_node.attachNewNode("mast")
        # Obere bzw. untere Balken
        top_bar = self.create_box(1, 0.1, 0.1, (0.2, 0.2, 0.2, 1))
        top_bar_node = mast_node.attachNewNode(top_bar)
        top_bar_node.setPos(0, 0, 0.9)
        bottom_bar = self.create_box(1, 0.1, 0.1, (0.2, 0.2, 0.2, 1))
        bottom_bar_node = mast_node.attachNewNode(bottom_bar)
        bottom_bar_node.setPos(0, 0, 0)
        # Linker und rechter Balken (in Z-Richtung zwischen bottom und top, aber nur an den Seiten)
        left_bar = self.create_box(0.1, 0.1, 0.8, (0.2, 0.2, 0.2, 1))
        left_bar_node = mast_node.attachNewNode(left_bar)
        left_bar_node.setPos(0, 0, 0.1)
        right_bar = self.create_box(0.1, 0.1, 0.8, (0.2, 0.2, 0.2, 1))
        right_bar_node = mast_node.attachNewNode(right_bar)
        right_bar_node.setPos(0.9, 0, 0.1)
        mast_node.setTwoSided(True)
        # Positioniere den Mast wie bisher
        mast_node.setPos(0, 0.2, 1.2)

        vehicle_node.setPos(-0.5, 0, 0)
        return vehicle_node

    def add_rectangle_to_fork(self, fork_node):
        """
        Fügt dem Fork-Knoten einen Rahmen (ohne Füllung) hinzu, der
        in lokalen XY-Koordinaten von (0,0) bis (1,1) auf der oberen Fläche
        (jetzt z=0.101, da die Höhe des Fork beträgt 0.1) liegt.
        Zusätzlich werden zwei Diagonalen eingezeichnet.
        Der Marker am Schnittpunkt der Diagonalen wird um 0.5 in Z angehoben,
        sodass er bei z=0.601 liegt.
        """
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(1.0, 0.5, 0.0, 1)  # Orange

        ls.moveTo(0, 0, 0.101)
        ls.drawTo(1, 0, 0.101)
        ls.drawTo(1, 1, 0.101)
        ls.drawTo(0, 1, 0.101)
        ls.drawTo(0, 0, 0.101)

        ls.moveTo(0, 0, 0.101)
        ls.drawTo(1, 1, 0.101)
        ls.moveTo(1, 0, 0.101)
        ls.drawTo(0, 1, 0.101)

        fork_node.attachNewNode(ls.create())

        # Marker: Ursprung der Diagonalen: (0.5, 0.5, 0.101) → Marker bei z=0.101+0.5 = 0.601
        point = loader.loadModel("models/smiley")
        point.setScale(0.05)
        point.setPos(0.5, 0.5, 0.601)
        point.setColor(1, 1, 1, 0.5)  # transparent
        point.setTransparency(True)
        point.reparentTo(fork_node)

    def create_box(self, width, depth, height, color):
        fmt = GeomVertexFormat.getV3n3cp()
        vdata = GeomVertexData("box", fmt, Geom.UHStatic)
        vertex = GeomVertexWriter(vdata, "vertex")
        normal = GeomVertexWriter(vdata, "normal")
        col = GeomVertexWriter(vdata, "color")

        # Unterseite
        for v in [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, -1)
            col.addData4f(*color)
        # Oberseite
        for v in [(0, 0, height), (width, 0, height), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 0, 1)
            col.addData4f(*color)
        # Vorderseite
        for v in [(0, 0, 0), (width, 0, 0), (width, 0, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, -1, 0)
            col.addData4f(*color)
        # Rückseite
        for v in [(0, depth, 0), (width, depth, 0), (width, depth, height), (0, depth, height)]:
            vertex.addData3f(*v)
            normal.addData3f(0, 1, 0)
            col.addData4f(*color)
        # Linke Seite
        for v in [(0, 0, 0), (0, depth, 0), (0, depth, height), (0, 0, height)]:
            vertex.addData3f(*v)
            normal.addData3f(-1, 0, 0)
            col.addData4f(*color)
        # Rechte Seite
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

    def update_cable(self, task):
        t = task.time
        new_height = 0.5 + 0.5 * math.sin(t * 2.0)  # Werte zwischen 0 und 1
        self.fork_node.setZ(new_height)
        self.fork_label['text'] = f"Fork Höhe: {new_height:.2f}m"
        return Task.cont


if __name__ == "__main__":
    app = SimpleSimulation()
    app.run()
