from direct.showbase.ShowBase import ShowBase
from panda3d.core import LineSegs, NodePath
from direct.interval.IntervalGlobal import Sequence, Parallel, LerpPosInterval, Func
import math
import random


class LagerSimulation(ShowBase):
    def __init__(self):
        super().__init__()

        # Parameter für den Betriebsmodus: "einlagern" oder "auslagerung"
        # Hier testen wir aktuell den Auslagerungsmodus
        self.mode = "auslagerung"

        # Parameter für das Lagerlayout
        self.num_storage_x = 10  # 10 Lagerplätze in X-Richtung
        self.num_blocks = 5      # ergibt 2*5+2 = 12 Reihen -> 6 Gassen
        self.num_storage_y = 2 * self.num_blocks + 2
        self.num_levels = 3
        self.level_gap = 0.2
        self.box_size = 1.0
        self.gap = 0.5
        self.aisle_gap = 2.0
        self.inner_gap = 0.1

        # Berechnung der Regalreihen-Positionen (Y-Achse)
        total_rows = self.num_storage_y
        raw_row_positions = []
        for r in range(total_rows):
            if r == 0:
                raw_row_positions.append(0)
            else:
                gap_y = self.aisle_gap if r % 2 == 1 else self.inner_gap
                raw_row_positions.append(raw_row_positions[-1] + self.box_size + gap_y)

        raw_min = raw_row_positions[0] - self.box_size / 2
        raw_max = raw_row_positions[-1] + self.box_size / 2
        center_y = (raw_min + raw_max) / 2
        offset_y = -center_y
        self.row_positions = [r + offset_y for r in raw_row_positions]

        # X-Positionierung (zentriert)
        total_width = self.num_storage_x * self.box_size + (self.num_storage_x - 1) * self.gap
        offset_x = -total_width / 2 + self.box_size / 2
        self.offset_x = offset_x

        # Erzeuge Regalzellen
        self.storage_cells = []
        base_z = self.box_size / 2
        for row_index, row_y in enumerate(self.row_positions):
            for col in range(self.num_storage_x):
                for level in range(self.num_levels):
                    x = offset_x + col * (self.box_size + self.gap)
                    y = row_y
                    z = base_z + level * (self.box_size + self.level_gap)
                    cell_node = self.create_storage_box(self.box_size, (0, 1, 0, 1))
                    cell_node.setPos(x, y, z)
                    cell_node.reparentTo(self.render)
                    self.storage_cells.append({
                        "node": cell_node,
                        "occupied": False,
                        "pos": (x, y, z),
                        "row": row_index,
                        "col": col,
                        "level": level
                    })

        # Pre-fill: 70% der Zellen werden belegt
        total_cells = len(self.storage_cells)
        num_pre_fill = int(total_cells * 0.7)
        cells_to_fill = random.sample(self.storage_cells, num_pre_fill)
        for cell in cells_to_fill:
            cell["occupied"] = True
            pos = cell["pos"]
            cell["node"].removeNode()
            # Roter Kasten als belegter Lagerplatz
            occupied_box = self.create_storage_box(self.box_size, (1, 0, 0, 1))
            occupied_box.setPos(pos)
            occupied_box.reparentTo(self.render)
            cell["node"] = occupied_box
            # Zeige zusätzlich eine gelbe LE im belegten Lagerplatz an
            load_unit = self.create_storage_box(self.box_size * 0.8, (1, 1, 0, 1))
            load_unit.setPos(pos)
            load_unit.reparentTo(self.render)
            # Speichere die Referenz zur gelben LE in der Zelle:
            cell["load_unit_node"] = load_unit

        # Grenzen der Regale
        self.shelf_bottom = min(self.row_positions) - self.box_size / 2
        self.shelf_top = max(self.row_positions) + self.box_size / 2
        self.shelf_left = offset_x - self.box_size / 2
        self.shelf_right = offset_x + total_width - self.box_size / 2

        # Berechne sichere Korridore (je 2 Reihen ergeben 6 Gassen)
        self.safe_corridors = []
        for i in range(0, self.num_storage_y, 2):
            corridor = (self.row_positions[i] + self.row_positions[i + 1]) / 2
            self.safe_corridors.append(corridor)

        # LE‑Quelle (Ladeeinheiten-Quelle) wird hier nur für den Einlagerungsmodus genutzt
        source_y = self.shelf_bottom - 3.0
        self.source_pos = (0, source_y, base_z)
        source_indicator = self.create_storage_box(self.box_size * 1.2, (0, 0, 1, 1))
        source_indicator.setPos(self.source_pos)
        source_indicator.reparentTo(self.render)

        # Auslagerungsstation
        unload_offset = (self.box_size * 2.0, 0, 0)
        self.unload_pos = (self.source_pos[0] + unload_offset[0],
                           self.source_pos[1] + unload_offset[1],
                           self.source_pos[2] + unload_offset[2])
        unload_indicator = self.create_storage_box(self.box_size * 1.2, (1, 0, 0, 1))
        unload_indicator.setPos(self.unload_pos)
        unload_indicator.reparentTo(self.render)

        # Kamera-Setup
        self.disableMouse()
        center_x = (self.shelf_left + self.shelf_right) / 2
        center_y_bound = (self.shelf_bottom + self.shelf_top) / 2
        self.camera_target = (center_x, center_y_bound, base_z)
        self.camera_radius = max(self.shelf_right - self.shelf_left, self.shelf_top - self.shelf_bottom) + 10
        self.camera_h = 90.0
        self.camera_p = 15.0
        self.updateCameraOrbit()

        # Kamera-Steuerung
        self.dragging = False
        self.lastMousePos = None

        # Shuttle‑Parameter
        self.load_unit_speed = 7.0
        self.max_shuttles = 2
        self.active_shuttles = 0
        self.taskMgr.doMethodLater(1.33, self.spawn_load_unit, "SpawnLoadUnitTask")

    def updateCameraOrbit(self):
        h_rad = math.radians(self.camera_h)
        p_rad = math.radians(self.camera_p)
        cx, cy, cz = self.camera_target
        r = self.camera_radius
        cam_x = cx + r * math.cos(p_rad) * math.sin(h_rad)
        cam_y = cy + r * math.cos(p_rad) * math.cos(h_rad)
        cam_z = cz + r * math.sin(p_rad)
        self.camera.setPos(cam_x, cam_y, cam_z)
        self.camera.lookAt(cx, cy, cz)

    def startCameraDrag(self):
        self.dragging = True
        if self.mouseWatcherNode.hasMouse():
            self.lastMousePos = (self.mouseWatcherNode.getMouseX(),
                                 self.mouseWatcherNode.getMouseY())

    def stopCameraDrag(self):
        self.dragging = False
        self.lastMousePos = None

    def updateCameraTask(self, task):
        if self.dragging and self.mouseWatcherNode.hasMouse():
            currentMousePos = (self.mouseWatcherNode.getMouseX(),
                               self.mouseWatcherNode.getMouseY())
            if self.lastMousePos is not None:
                dx = currentMousePos[0] - self.lastMousePos[0]
                dy = currentMousePos[1] - self.lastMousePos[1]
                self.camera_h += dx * 100
                self.camera_p -= dy * 100
                self.camera_p = max(-80, min(80, self.camera_p))
                self.updateCameraOrbit()
            self.lastMousePos = currentMousePos
        return task.cont

    def create_storage_box(self, size, color):
        half = size / 2.0
        ls = LineSegs()
        ls.setThickness(2.0)
        ls.setColor(*color)
        ls.moveTo(-half, -half, -half)
        ls.drawTo(half, -half, -half)
        ls.drawTo(half, half, -half)
        ls.drawTo(-half, half, -half)
        ls.drawTo(-half, -half, -half)
        ls.moveTo(-half, -half, half)
        ls.drawTo(half, -half, half)
        ls.drawTo(half, half, half)
        ls.drawTo(-half, half, half)
        ls.drawTo(-half, -half, half)
        ls.moveTo(-half, -half, -half)
        ls.drawTo(-half, -half, half)
        ls.moveTo(half, -half, -half)
        ls.drawTo(half, -half, half)
        ls.moveTo(half, half, -half)
        ls.drawTo(half, half, half)
        ls.moveTo(-half, half, -half)
        ls.drawTo(-half, half, half)
        return NodePath(ls.create())

    def spawn_load_unit(self, task):
        if self.active_shuttles >= self.max_shuttles:
            return task.again

        # Auswahl der Zielzelle abhängig vom Modus:
        if self.mode == "einlagern":
            available_cells = [cell for cell in self.storage_cells if not cell["occupied"]]
            if not available_cells:
                print("Lager voll!")
                return task.again
            chosen_cell = random.choice(available_cells)
            start_point = self.source_pos
            # Erzeuge eine neue LE (gelb) als Fracht
            load_unit = self.create_storage_box(self.box_size * 0.8, (1, 1, 0, 1))
            load_unit.setPos(start_point)
            load_unit.reparentTo(self.render)
        else:  # auslagerung
            # Für die Auslagerung wählt man eine belegte Zelle, in der auch eine gelbe LE gespeichert ist
            available_cells = [cell for cell in self.storage_cells if cell["occupied"] and cell.get("load_unit_node")]
            if not available_cells:
                print("Keine LE im Lager vorhanden!")
                return task.again
            chosen_cell = random.choice(available_cells)
            start_point = self.unload_pos
            # Anstatt eine neue LE zu erzeugen, holen wir die vorhandene gelbe LE aus der Zelle.
            load_unit = chosen_cell["load_unit_node"]
            load_unit.setPos(chosen_cell["pos"])
            # Entferne die Referenz, damit nicht versehentlich dieselbe LE mehrfach verwendet wird.
            chosen_cell["load_unit_node"] = None

        # Erzeuge Shuttle (lila) am Startpunkt
        shuttle = self.create_storage_box(self.box_size * 1.2, (0.5, 0, 0.5, 1))
        shuttle.setPos(start_point)
        shuttle.reparentTo(self.render)
        self.active_shuttles += 1

        base_z = self.box_size / 2
        source = start_point
        margin = 0.5
        side_x_right = self.shelf_right + margin
        side_x_left = self.shelf_left - margin

        forward_offset = self.box_size * 1.5
        forward_point = (source[0], source[1] + forward_offset, base_z)

        target_x, target_y, target_z = chosen_cell["pos"]
        lane = chosen_cell["row"] // 2
        safe_y = self.safe_corridors[lane]

        if target_x >= 0:
            inbound_points = [
                source,
                forward_point,
                (side_x_right, forward_point[1], base_z),
                (side_x_right, safe_y, base_z),
                (target_x, safe_y, base_z),
                (target_x, safe_y, target_z),
                (target_x, target_y, target_z)
            ]
            return_points = [
                (target_x, target_y, target_z),
                (target_x, safe_y, target_z),
                (target_x, safe_y, base_z),
                (side_x_right, safe_y, base_z),
                (side_x_right, forward_point[1], base_z),
                forward_point,
                source
            ]
        else:
            inbound_points = [
                source,
                forward_point,
                (side_x_left, forward_point[1], base_z),
                (side_x_left, safe_y, base_z),
                (target_x, safe_y, base_z),
                (target_x, safe_y, target_z),
                (target_x, target_y, target_z)
            ]
            return_points = [
                (target_x, target_y, target_z),
                (target_x, safe_y, target_z),
                (target_x, safe_y, base_z),
                (side_x_left, safe_y, base_z),
                (side_x_left, forward_point[1], base_z),
                forward_point,
                source
            ]

        speed = self.load_unit_speed
        inbound_durations = [math.dist(inbound_points[i], inbound_points[i + 1]) / speed
                             for i in range(len(inbound_points) - 1)]
        return_durations = [math.dist(return_points[i], return_points[i + 1]) / speed
                            for i in range(len(return_points) - 1)]

        # Erzeuge die Inbound-Intervalle:
        inbound_shuttle_intervals = []
        inbound_load_intervals = []
        if self.mode == "einlagern":
            # Beide, Shuttle und LE, bewegen sich gemeinsam von der Quelle zum Lagerplatz.
            for i in range(len(inbound_durations)):
                interval_shuttle = LerpPosInterval(shuttle, inbound_durations[i], inbound_points[i + 1])
                interval_load = LerpPosInterval(load_unit, inbound_durations[i], inbound_points[i + 1])
                inbound_shuttle_intervals.append(interval_shuttle)
                inbound_load_intervals.append(interval_load)
        else:
            # Im Auslagerungsmodus fährt zunächst nur das Shuttle vom Unload-Punkt zum Lagerplatz;
            # die gelbe LE bleibt anfangs in der Zelle.
            for i in range(len(inbound_durations)):
                interval_shuttle = LerpPosInterval(shuttle, inbound_durations[i], inbound_points[i + 1])
                inbound_shuttle_intervals.append(interval_shuttle)
            # Keine Intervalle für die LE inbound.

        # Erzeuge die Return-Intervalle:
        return_shuttle_intervals = []
        return_load_intervals = []
        if self.mode == "einlagern":
            # Beim Einlagern fährt nur das Shuttle zurück.
            for i in range(len(return_durations)):
                r_int = LerpPosInterval(shuttle, return_durations[i], return_points[i + 1])
                return_shuttle_intervals.append(r_int)
        else:
            # Beim Auslagern sollen Shuttle und LE gemeinsam von der Zelle zurück zur Auslagerungsstation fahren.
            for i in range(len(return_durations)):
                r_int_shuttle = LerpPosInterval(shuttle, return_durations[i], return_points[i + 1])
                r_int_load = LerpPosInterval(load_unit, return_durations[i], return_points[i + 1])
                return_shuttle_intervals.append(r_int_shuttle)
                return_load_intervals.append(r_int_load)

        # Beim Auslagerungsmodus: Ankunft im Lagerplatz – LE vom Regal aufnehmen ("anheften")
        def attach_load_unit():
            load_unit.setPos(shuttle.getPos())

        def update_cell_status():
            pos = chosen_cell["node"].getPos()
            chosen_cell["node"].removeNode()
            if self.mode == "einlagern":
                new_box = self.create_storage_box(self.box_size, (1, 0, 0, 1))
                chosen_cell["occupied"] = True
            else:
                new_box = self.create_storage_box(self.box_size, (0, 1, 0, 1))
                chosen_cell["occupied"] = False
            new_box.setPos(pos)
            new_box.reparentTo(self.render)
            chosen_cell["node"] = new_box

        def decrement_active_shuttles():
            self.active_shuttles -= 1

        if self.mode == "einlagern":
            inbound_sequence = []
            for i in range(len(inbound_shuttle_intervals)):
                inbound_sequence.append(Parallel(inbound_shuttle_intervals[i], inbound_load_intervals[i]))
            route = Sequence(
                *inbound_sequence,
                Func(update_cell_status),
                *return_shuttle_intervals,
                Func(decrement_active_shuttles)
            )
        else:
            route = Sequence(
                *inbound_shuttle_intervals,
                Func(attach_load_unit),
                Func(update_cell_status),
                *[Parallel(return_shuttle_intervals[i], return_load_intervals[i])
                  for i in range(len(return_shuttle_intervals))],
                Func(decrement_active_shuttles)
            )
        route.start()

        return task.again


if __name__ == "__main__":
    simulation = LagerSimulation()
    simulation.accept("mouse1", simulation.startCameraDrag)
    simulation.accept("mouse1-up", simulation.stopCameraDrag)
    simulation.taskMgr.add(simulation.updateCameraTask, "UpdateCameraTask")
    simulation.run()