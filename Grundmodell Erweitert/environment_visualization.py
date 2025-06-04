# environment_visualization.py

from panda3d.core import (
    LineSegs, LColor, Vec3, GeomVertexFormat, GeomVertexData,
    GeomVertexWriter, GeomLines, Geom, GeomNode, TextNode, CardMaker,
    AmbientLight, DirectionalLight, Vec2
)
import math

DEFAULT_LABEL_SCALE = 3   # Hier kannst du den Wert später einfach anpassen

def attach_label(node, offset=Vec3(1, 0, 0), scale=None):
    if scale is None:
        scale = DEFAULT_LABEL_SCALE  # Nutzt den zentral definierten Standardwert

    text_node = TextNode("node_label")
    text_node.setText(node.getName())
    text_node.setAlign(TextNode.ACenter)

    label_np = node.attachNewNode(text_node)
    label_np.setScale(scale)
    label_np.setPos(offset)
    label_np.setBillboardAxis()

    # Speichere den Label-Node als PythonTag am übergebenen Node
    node.setPythonTag("label_node", label_np)

    return label_np




class NodeManager:
    def __init__(self, render):
        self.render = render
        self.nodes = {}
        self.counters = {"blue": 0, "green": 0, "yellow": 0}

    def register_node(self, node, node_type):
        self.counters[node_type] += 1
        unique_name = f"{node_type}_node_{self.counters[node_type]}"
        node.setName(unique_name)
        self.nodes[unique_name] = node
        return unique_name

    def create_blue_dot(self, loader, pos, scale=0.1):
        blue_dot = loader.loadModel("models/misc/sphere")
        blue_dot.setScale(scale)
        blue_dot.setColor(LColor(0, 0, 1, 1))
        blue_dot.setPos(pos)
        blue_dot.reparentTo(self.render)
        self.register_node(blue_dot, "blue")
        attach_label(blue_dot, Vec3(2, 0, 0))
        return blue_dot

    def create_green_dot(self, loader, pos, scale=0.1):
        green_dot = loader.loadModel("models/misc/sphere")
        green_dot.setScale(scale)
        green_dot.setColor(LColor(0, 1, 0, 1))
        green_dot.setPos(pos)
        green_dot.reparentTo(self.render)
        self.register_node(green_dot, "green")
        attach_label(green_dot, Vec3(2, 0, 0))
        return green_dot

    def create_yellow_dot(self, loader, pos, scale=0.1):
        # Erzeugt einen gelben Punkt mit eigenem Zähler und Beschriftung
        yellow_dot = loader.loadModel("models/misc/sphere")
        yellow_dot.setScale(scale)
        yellow_dot.setColor(LColor(1, 1, 0, 1))  # Gelb
        yellow_dot.setPos(pos)
        yellow_dot.reparentTo(self.render)
        self.register_node(yellow_dot, "yellow")
        attach_label(yellow_dot, Vec3(2, 0, 0))
        return yellow_dot

    def list_all_nodes(self):
        return list(self.nodes.keys())

    def get_node(self, unique_name):
        return self.nodes.get(unique_name)


class EnvironmentVisualizer:
    def __init__(self, render, loader):
        self.render = render
        self.loader = loader
        self.node_manager = NodeManager(render)

    def setup_environment(self):
        # Grundaufbau: Ursprung, Licht, Bodenraster, Wand
        origin_node = self.draw_origin()
        self.erzeuge_licht()
        self.erzeuge_bodenraster(center_extent=70, cell_size=1)
        self.create_wall()

        # Stationen: Annahme & Abgabe
        annahme_dict = self.create_annahme_stations()
        abgabe_dict = self.create_abgabe_stations()
        abgabe_connection_line = self.connect_blue_dots_line(
            abgabe_dict["abgabe_blue_dots"],
            color=LColor(1, 1, 1, 1),
            thickness=2.0
        )
        if abgabe_connection_line:
            abgabe_dict["abgabe_white_lines"].append(abgabe_connection_line)

        # Garagen: Hier wird die angepasste Methode aufgerufen
        garagen_stations, garagen_parking_points = self.create_garagen_stations()
        garage_connection_line = self.connect_garagen_blue_dots_line(
            color=LColor(1, 1, 1, 1),
            thickness=2.0
        )

        # Weitere Verbindungen und gelbe Punkte (wie bisher)
        self.draw_edge_between_blue_nodes("blue_node_26", "blue_node_21")
        self.connect_annahme_abgabe_blue_dots(color=LColor(1, 1, 1, 1), thickness=2.0)
        extra_blue_line = self.draw_edge_between_blue_nodes_10_22()

        yellow_station_points = self.create_yellow_station_points()
        yellow_abgabe_points = self.create_yellow_abgabe_points()
        yellow_garage_points = self.create_yellow_garage_points()

        self.yellow_connection_points = []
        for blue_annahme, blue_abgabe in zip(self.annahme_blue_dot_list, self.abgabe_blue_dots):
            yellow_annahme, yellow_abgabe = self.create_yellow_points_for_connection(blue_annahme, blue_abgabe)
            self.yellow_connection_points.append((yellow_annahme, yellow_abgabe))

        env = {
            "origin": origin_node,
            "wall_segments": self.wall_segments,
            "annahme_stations": annahme_dict["annahme_stations"],
            "station_blue_dots": annahme_dict["station_blue_dots"],
            "white_lines": annahme_dict["white_lines"],
            "annahme_connecting_line": annahme_dict.get("connecting_line"),
            "abgabe_stations": abgabe_dict["abgabe_stations"],
            "abgabe_blue_dots": abgabe_dict["abgabe_blue_dots"],
            "abgabe_white_lines": abgabe_dict["abgabe_white_lines"],
            "abgabe_extra_blue_dot": abgabe_dict["abgabe_extra_blue_dot"],
            "abgabe_extra_line": abgabe_dict["abgabe_extra_line"],
            "garagen_stations": garagen_stations,
            "garagen_parking_points": garagen_parking_points,
            "yellow_station_points": yellow_station_points,
            "yellow_abgabe_points": yellow_abgabe_points,
            "yellow_garage_points": yellow_garage_points,
            "blue_line_10_22": extra_blue_line,
            "abgabe_connection_line": abgabe_connection_line,
            "garage_connection_line": garage_connection_line,
            "yellow_connection_points": self.yellow_connection_points
        }
        return env

    # ------------------------------
    # Grundlegende Umgebungsaufbauten
    # ------------------------------
    def draw_origin(self):
        ls = LineSegs()
        ls.setThickness(2)

        # X-Achse in Rot
        ls.setColor(LColor(1, 0, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(1, 0, 0)

        # Y-Achse in Grün
        ls.setColor(LColor(0, 1, 0, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 1, 0)

        # Z-Achse in Blau
        ls.setColor(LColor(0, 0, 1, 1))
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, 0, 1)

        origin_node = self.render.attachNewNode(ls.create())
        return origin_node

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

        # Horizontal lines
        y = min_line
        while y <= max_line:
            writer.addData3f(min_line, y, 0)
            writer.addData3f(max_line, y, 0)
            lines.addVertices(n_vertices, n_vertices + 1)
            n_vertices += 2
            y += cell_size

        # Vertical lines
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

        self.wall_segments = []
        wall_segment1 = self.add_wall_segment(p1, p2)
        wall_segment2 = self.add_wall_segment(p2, p3)
        wall_segment3 = self.add_wall_segment(p3, p4)
        wall_segment4 = self.add_wall_segment(p4, p1)
        self.wall_segments.extend([wall_segment1, wall_segment2, wall_segment3, wall_segment4])

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
        return wall_np

    # ------------------------------
    # Annahme-Stationen
    # ------------------------------
    def create_annahme_station(self, pos):
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(0, 1, 0, 1))
        # Eckpunkte
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
        station_points = [
            Vec3(0, 5, 0), Vec3(0, 10, 0), Vec3(0, 15, 0),
            Vec3(0, 20, 0), Vec3(0, 25, 0), Vec3(0, 30, 0),
            Vec3(0, 35, 0), Vec3(0, 40, 0), Vec3(0, 45, 0),
            Vec3(0, 50, 0)
        ]

        self.annahme_stations = []
        self.station_blue_dots = {}
        self.annahme_blue_dot_list = []  # Reihenfolge der blauen Marker
        self.annahme_white_lines = []    # Liste weißer Linien
        self.annahme_connecting_line = None

        for i, pt in enumerate(station_points, start=1):
            self.create_annahme_station(pt)
            station_dummy = self.render.attachNewNode(f"annahme_station_{i}")
            station_dummy.setPos(pt)
            self.annahme_stations.append(station_dummy)
            center = pt + Vec3(0.5, 0.5, 0.5)

            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            green_dot = self.node_manager.create_green_dot(self.loader, center + Vec3(0, 0, -0.5), 0.1)

            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            white_line_node = self.render.attachNewNode(line_seg.create())
            self.annahme_white_lines.append(white_line_node)

            blue_dot = self.node_manager.create_blue_dot(self.loader, end_line)
            self.station_blue_dots[station_dummy] = blue_dot
            self.annahme_blue_dot_list.append(blue_dot)

            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 1.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

            # Zusätzliche Markierungen (Kreuze)
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

            white_center = (start_line + end_line) * 0.5
            white_direction_vector = end_line - start_line
            if white_direction_vector.length() != 0:
                white_direction = Vec2(white_direction_vector.getX(), white_direction_vector.getY()).normalized()
            else:
                white_direction = Vec2(1, 0)
            station_dummy.setPythonTag("white_center", white_center)
            station_dummy.setPythonTag("white_direction", white_direction)

            self.annahme_connecting_line = self.connect_annahme_blue_dots_line(color=LColor(1, 1, 1, 1), thickness=2.0)

        return {
            "annahme_stations": self.annahme_stations,
            "station_blue_dots": self.station_blue_dots,
            "white_lines": self.annahme_white_lines,
            "connecting_line": self.annahme_connecting_line
        }

    # ------------------------------
    # Abgabe-Stationen
    # ------------------------------
    def create_abgabe_extra_blue_dot(self, base_blue_dot):
        from panda3d.core import Vec3, LineSegs, LColor
        start_point = base_blue_dot.getPos()
        end_point = start_point + Vec3(0, 3, 0)
        line_seg = LineSegs()
        line_seg.setThickness(2.0)
        line_seg.setColor(LColor(1, 1, 1, 1))
        line_seg.moveTo(start_point)
        line_seg.drawTo(end_point)
        extra_line_node = self.render.attachNewNode(line_seg.create())
        extra_blue_dot = self.node_manager.create_blue_dot(self.loader, end_point)
        return extra_blue_dot, extra_line_node

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
        from panda3d.core import Vec3, LColor, LineSegs, TextNode
        station_points = [
            Vec3(21, 5, 0), Vec3(21, 10, 0), Vec3(21, 15, 0),
            Vec3(21, 20, 0), Vec3(21, 25, 0), Vec3(21, 30, 0),
            Vec3(21, 35, 0), Vec3(21, 40, 0), Vec3(21, 45, 0),
            Vec3(21, 50, 0)
        ]
        self.abgabe_stations = []
        self.abgabe_blue_dots = []
        self.abgabe_white_lines = []
        self.abgabe_extra_line = None
        self.abgabe_extra_blue_dot = None

        for i, pt in enumerate(station_points, start=1):
            station_node = self.create_abgabe_station(pt)
            self.abgabe_stations.append(station_node)
            center = pt + Vec3(0.5, 0.5, 0.5)

            marker = self.loader.loadModel("models/misc/sphere")
            marker.setScale(0.15)
            marker.setColor(LColor(1, 1, 1, 1))
            marker.setPos(center)
            marker.reparentTo(self.render)

            green_dot = self.node_manager.create_green_dot(self.loader, center + Vec3(0, 0, -0.5), 0.1)

            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = center + Vec3(0, 0, -0.5)
            end_line = start_line + Vec3(-3, 0, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            white_line_node = self.render.attachNewNode(line_seg.create())
            self.abgabe_white_lines.append(white_line_node)

            blue_dot = self.node_manager.create_blue_dot(self.loader, end_line)
            self.abgabe_blue_dots.append(blue_dot)

            tn = TextNode("station_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x - 0.1, pt.y + 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)

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

        connection_line_node = self.connect_blue_dots_line(self.abgabe_blue_dots, color=LColor(1, 1, 1, 1),
                                                           thickness=2.0)
        if connection_line_node:
            self.abgabe_white_lines.append(connection_line_node)

        if len(self.abgabe_blue_dots) >= 10:
            base_blue_dot = self.abgabe_blue_dots[9]
            extra_blue_dot, extra_line_node = self.create_abgabe_extra_blue_dot(base_blue_dot)
            self.abgabe_extra_blue_dot = extra_blue_dot
            self.abgabe_extra_line = extra_line_node

        return {
            "abgabe_stations": self.abgabe_stations,
            "abgabe_blue_dots": self.abgabe_blue_dots,
            "abgabe_white_lines": self.abgabe_white_lines,
            "abgabe_extra_blue_dot": self.abgabe_extra_blue_dot,
            "abgabe_extra_line": self.abgabe_extra_line,
        }

    # ------------------------------
    # Garagen-Stationen
    # ------------------------------
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
        self.garagen_blue_dots = []
        self.garagen_stations = []
        self.garagen_parking_points = []
        self.garagen_green_nodes = []  # Neue Liste für die zusätzlichen grünen Punkte

        for i, pt in enumerate(station_points, start=1):
            self.create_garage_station(pt)
            self.add_garage_roof(pt)
            self.garagen_stations.append(pt)

            center = pt + Vec3(0.5, 0.5, 1.5)
            parkpunkt_pos = center + Vec3(0, 0, 0.7)
            # Erzeuge einen grünen Punkt an der Position des Parkpunkts
            green_park_dot = self.node_manager.create_green_dot(self.loader, parkpunkt_pos, scale=0.1)
            self.garagen_parking_points.append(green_park_dot)

            garage_base_center = pt + Vec3(0.5, 1.0, 0)

            line_seg = LineSegs()
            line_seg.setThickness(2.0)
            line_seg.setColor(LColor(1, 1, 1, 1))
            start_line = garage_base_center
            end_line = start_line + Vec3(0, -3, 0)
            line_seg.moveTo(start_line)
            line_seg.drawTo(end_line)
            self.render.attachNewNode(line_seg.create())

            blue_dot = self.node_manager.create_blue_dot(self.loader, end_line)
            self.garagen_blue_dots.append(blue_dot)

            # --- Neuer Code für den zusätzlichen grünen Punkt ---
            # Verwende die X- und Y-Koordinaten von garage_base_center, setze Z explizit auf 0:
            additional_green_pos = Vec3(garage_base_center.getX(), garage_base_center.getY(), 0)
            additional_green_dot = self.node_manager.create_green_dot(self.loader, additional_green_pos, 0.1)
            self.garagen_green_nodes.append(additional_green_dot)
            # -------------------------------------------------------



            tn = TextNode("garage_number")
            tn.setText(str(i))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(LColor(0, 0, 0, 1))
            tn_np = self.render.attachNewNode(tn)
            tn_np.setPos(pt.x + 0.5, pt.y - 0.5, 0.01)
            tn_np.setHpr(0, -90, 0)
        return self.garagen_stations, self.garagen_parking_points

    # ------------------------------
    # Verbindungen zwischen Blue-Dots
    # ------------------------------

    def connect_blue_dots_line(self, blue_dots, color=LColor(1, 1, 1, 1), thickness=2.0):
        """
        Verbinde eine Liste von Blue-Dot-NodePaths miteinander, indem eine durchgehende Linie gezeichnet wird.

        Parameter:
          blue_dots (Liste[NodePath]): Liste der Blue-Dotes, die verbunden werden sollen.
          color (LColor): Farbe der Linie (Standard: weiß).
          thickness (float): Linienstärke (Standard: 2.0).

        Rückgabewert:
          NodePath: Der NodePath, der die gezeichnete Linie repräsentiert, oder None, falls die Liste leer ist.
        """
        if not blue_dots:
            return None

        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(blue_dots[0].getPos())
        for dot in blue_dots[1:]:
            ls.drawTo(dot.getPos())
        connection_line_node = self.render.attachNewNode(ls.create())
        return connection_line_node

    def connect_annahme_blue_dots_line(self, color=LColor(1, 1, 1, 1), thickness=2.0):
        """
        Verbindet alle Blue-Dot-NodePaths der Annahme-Stationen (gespeichert in self.annahme_blue_dot_list)
        mit einer durchgehenden Linie.

        Parameter:
          color (LColor): Farbe der Linie (Standard: weiß)
          thickness (float): Linienstärke (Standard: 2.0)

        Rückgabewert:
          NodePath: Der NodePath der gezeichneten Linie, oder None wenn keine Blue-Dots vorhanden sind.
        """
        if not self.annahme_blue_dot_list:
            return None

        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(self.annahme_blue_dot_list[0].getPos())
        for blue_dot in self.annahme_blue_dot_list[1:]:
            ls.drawTo(blue_dot.getPos())
        connection_line_node = self.render.attachNewNode(ls.create())
        return connection_line_node

    def connect_garagen_blue_dots_line(self, color=LColor(1, 1, 1, 1), thickness=2.0):
        """
        Verbinde alle Blue-Dot-NodePaths der Garagenstationen (gespeichert in self.garagen_blue_dots)
        mit einer durchgehenden Linie.

        Parameter:
          color (LColor): Farbe der Linie (Standard: weiß)
          thickness (float): Linienstärke (Standard: 2.0)

        Rückgabewert:
          NodePath: Der NodePath der gezeichneten Linie, oder None, wenn keine Blue-Dots vorhanden sind.
        """
        if not self.garagen_blue_dots:
            return None

        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(self.garagen_blue_dots[0].getPos())
        for blue_dot in self.garagen_blue_dots[1:]:
            ls.drawTo(blue_dot.getPos())
        garage_connection_line = self.render.attachNewNode(ls.create())
        return garage_connection_line

    def draw_edge_between_blue_nodes(self, blue_node_21, blue_node_26):
        node1 = self.node_manager.get_node(blue_node_21)
        node2 = self.node_manager.get_node(blue_node_26)
        if not node1 or not node2:
            print(f"Ein oder beide Blue Nodes wurden nicht gefunden: {blue_node_21}, {blue_node_26}")
            return None
        pos1 = node1.getPos()
        pos2 = node2.getPos()
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(1, 1, 1, 1))
        ls.moveTo(pos1)
        ls.drawTo(pos2)
        edge_node = self.render.attachNewNode(ls.create())
        return edge_node

    def draw_edge_between_blue_nodes_10_22(self):
        node10 = self.node_manager.get_node("blue_node_10")
        node22 = self.node_manager.get_node("blue_node_22")
        if not node10 or not node22:
            print("Ein oder beide Blue Nodes wurden nicht gefunden: blue_node_10, blue_node_22")
            return None
        pos10 = node10.getPos()
        pos22 = node22.getPos()
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(LColor(1, 1, 1, 1))
        ls.moveTo(pos10)
        ls.drawTo(pos22)
        extra_edge = self.render.attachNewNode(ls.create())
        return extra_edge

    def connect_annahme_abgabe_blue_dots(self, color=LColor(1, 1, 1, 1), thickness=2.0):
        if not hasattr(self, "annahme_blue_dot_list") or not hasattr(self, "abgabe_blue_dots"):
            print("Es sind nicht alle blauen Punkte vorhanden!")
            return
        if len(self.annahme_blue_dot_list) != len(self.abgabe_blue_dots):
            print("Die Anzahl der blauen Punkte der Annahme- und Abgabestationen stimmt nicht überein!")
            return
        for blue_annahme, blue_abgabe in zip(self.annahme_blue_dot_list, self.abgabe_blue_dots):
            ls = LineSegs()
            ls.setThickness(thickness)
            ls.setColor(color)
            ls.moveTo(blue_annahme.getPos())
            ls.drawTo(blue_abgabe.getPos())
            self.render.attachNewNode(ls.create())

    # ------------------------------
    # Gelbe Punkte an der Linie/Stationen
    # ------------------------------
    def create_yellow_points_for_connection(self, blue_annahme, blue_abgabe,
                                            shift_annahme=Vec3(3, 0, 0),
                                            shift_abgabe=Vec3(-2, 0, 0),
                                            scale=0.1):
        """
        Erzeugt für eine Verbindung zwischen einem Annahme- und einem Abgabe-Blue-Dot
        jeweils einen gelben Punkt und beschriftet diese fortlaufend.

        Ausgehend vom Annahme-Punkt wird der gelbe Punkt um 'shift_annahme' verschoben
        (Standard: Vec3(3, 0, 0)), und vom Abgabe-Punkt um 'shift_abgabe'
        (Standard: Vec3(-2, 0, 0)).

        Parameter:
          blue_annahme (NodePath): Blue-Dot der Annahme-Station.
          blue_abgabe (NodePath): Blue-Dot der Abgabe-Station.
          shift_annahme (Vec3, optional): Verschiebungsvektor für den Annahme-Punkt.
          shift_abgabe (Vec3, optional): Verschiebungsvektor für den Abgabe-Punkt.
          scale (float, optional): Skalierung der gelben Punkte (Standard: 0.1).

        Rückgabewert:
          tuple: (yellow_annahme, yellow_abgabe) – die erzeugten gelben Punkte als NodePaths.
        """
        # Berechne die Position des gelben Punktes bei der Annahme-Station
        yellow_annahme_pos = blue_annahme.getPos() + shift_annahme
        yellow_annahme = self.node_manager.create_yellow_dot(self.loader, yellow_annahme_pos, scale)

        # Berechne die Position des gelben Punktes bei der Abgabe-Station
        yellow_abgabe_pos = blue_abgabe.getPos() + shift_abgabe
        yellow_abgabe = self.node_manager.create_yellow_dot(self.loader, yellow_abgabe_pos, scale)

        return yellow_annahme, yellow_abgabe

    def create_yellow_end_points_on_line(self, start_dot, end_dot, offset=3.0, scale=0.1):
        start_pos = start_dot.getPos(self.render)
        end_pos = end_dot.getPos(self.render)
        direction = end_pos - start_pos
        norm = direction.length()
        if norm == 0:
            print("Start- und Endpunkt sind identisch – gelbe Punkte können nicht erstellt werden.")
            return None, None
        direction_normalized = direction / norm
        yellow_start_pos = start_pos + (direction_normalized * offset)
        yellow_end_pos = end_pos - (direction_normalized * offset)
        yellow_point_start = self.node_manager.create_blue_dot(self.loader, yellow_start_pos, scale)
        for child in yellow_point_start.getChildren():
            if child.getName() == "node_label":
                child.removeNode()
        yellow_point_start.setColor(LColor(1, 1, 0, 1))
        yellow_point_end = self.node_manager.create_blue_dot(self.loader, yellow_end_pos, scale)
        for child in yellow_point_end.getChildren():
            if child.getName() == "node_label":
                child.removeNode()
        yellow_point_end.setColor(LColor(1, 1, 0, 1))
        return yellow_point_start, yellow_point_end

    def create_yellow_station_points(self, offset=3.0, scale=0.1):
        yellow_station_points = []
        for blue_dot in self.annahme_blue_dot_list:
            pos = blue_dot.getPos(self.render)
            new_pos = pos + Vec3(0, offset, 0)
            yellow_point = self.node_manager.create_yellow_dot(self.loader, new_pos, scale)
            yellow_station_points.append(yellow_point)

        return yellow_station_points

    def create_yellow_abgabe_points(self, offset=3.0, scale=0.1):
        yellow_abgabe_points = []

        for blue_dot in self.abgabe_blue_dots:
            pos = blue_dot.getPos(self.render)
            new_pos = pos + Vec3(0, offset, 0)
            yellow_point = self.node_manager.create_yellow_dot(self.loader, new_pos, scale)
            yellow_abgabe_points.append(yellow_point)

        return yellow_abgabe_points

    def create_yellow_garage_points(self, offset=3.0, scale=0.1):
        yellow_garage_points = []
        for idx, blue_dot in enumerate(self.garagen_blue_dots):
            if idx == 4:
                continue  # Garage 5 überspringen
            pos = blue_dot.getPos(self.render)
            new_pos = pos + Vec3(offset, 0, 0)
            # Verwende hier direkt den Node Manager, um einen gelben Punkt zu erzeugen
            yellow_point = self.node_manager.create_yellow_dot(self.loader, new_pos, scale)
            yellow_garage_points.append(yellow_point)
        return yellow_garage_points

    def add_cross_on_face(self, corners, color=LColor(1, 1, 1, 1), thickness=1.5):
        ls = LineSegs()
        ls.setThickness(thickness)
        ls.setColor(color)
        ls.moveTo(corners[0])
        ls.drawTo(corners[2])
        ls.moveTo(corners[1])
        ls.drawTo(corners[3])
        return self.render.attachNewNode(ls.create())
