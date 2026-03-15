from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor, QPixmap, QFontMetrics
from PyQt5.QtCore import Qt

class BaseMapWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(400, 300)
        self.map_pixmap = None
        self.map_world_w = 0.0
        self.map_world_h = 0.0
        self.x_axis = 'right'
        self.shapes = []  # list of dict: {x, y, color, shape, label}
        self.set_axes('right')  # default axes
        # 新增：用于存储阴影区域（圆形），每个元素为 {'center': (x, y), 'radius': r}
        self.shadow_regions = []
        self._drawing_shadow = False
        self._shadow_start = None
        self._shadow_end = None
        self.last_paint_params = {}

    def load_map(self, image_path: str, scale: float = 1.0):
        pix = QPixmap(image_path)
        if pix and not pix.isNull():
            self.map_pixmap = pix
            self.map_world_w = pix.width() * scale
            self.map_world_h = pix.height() * scale
            self.update()

    def set_axes(self, x_axis: str = 'right'):
        """
        设置x轴正方向，支持'up'/'down'/'left'/'right'。
        y轴正方向自动为x轴正方向逆时针旋转90度。
        """
        if x_axis not in ('up', 'down', 'left', 'right'):
            raise ValueError("x_axis must be 'up', 'down', 'left', or 'right'")
        self.x_axis = x_axis
        # y_axis自动推导
        mapping = {'up': 'left', 'left': 'down', 'down': 'right', 'right': 'up'}
        self.y_axis = mapping[x_axis]

    def world_to_pixel(self, x, y, px, py, pw, ph, scale):
        """
        世界坐标 (x, y) 转换为像素坐标 (px_, py_)
        px, py: 地图左上角像素坐标
        pw, ph: 地图像素宽高
        scale: 像素/世界单位
        """
        # 地图中心像素坐标
        cx = px + pw / 2
        cy = py + ph / 2
        # 根据坐标系方向计算偏移量
        if self.x_axis == 'right':  # y-axis: up
            dx = x * scale
            dy = -y * scale
        elif self.x_axis == 'left':  # y-axis: down
            dx = -x * scale
            dy = y * scale
        elif self.x_axis == 'up':  # y-axis: left
            dx = -y * scale
            dy = -x * scale
        elif self.x_axis == 'down':  # y-axis: right
            dx = y * scale
            dy = x * scale
        else:
            dx, dy = 0, 0  # fallback
        px_ = cx + dx
        py_ = cy + dy
        return px_, py_

    def pixel_to_world(self, px_, py_, px, py, pw, ph, scale):
        """
        像素坐标 (px_, py_) 转换为世界坐标 (x, y)
        """
        if scale == 0:
            return 0, 0
        # 地图中心像素坐标
        cx = px + pw / 2
        cy = py + ph / 2
        dx = px_ - cx
        dy = py_ - cy
        # 根据坐标系方向反向计算
        if self.x_axis == 'right':  # y-axis: up
            x = dx / scale
            y = -dy / scale
        elif self.x_axis == 'left':  # y-axis: down
            x = -dx / scale
            y = dy / scale
        elif self.x_axis == 'up':  # y-axis: left
            x = -dy / scale
            y = -dx / scale
        elif self.x_axis == 'down':  # y-axis: right
            x = dy / scale
            y = dx / scale
        else:
            x, y = 0, 0  # fallback
        return x, y

    def clear_shapes(self):
        self.shapes = []
        self.update()

    def add_shape(self, x, y, color, shape, label=None):
        self.shapes.append({'x': x, 'y': y, 'color': color, 'shape': shape, 'label': label})
        self.update()

    def set_shapes(self, shapes):
        self.shapes = shapes
        self.update()

    def mousePressEvent(self, a0):
        if a0.button() == Qt.LeftButton:
            self._drawing_shadow = True
            self._shadow_start = a0.pos()
            self._shadow_end = a0.pos()
            self.update()

    def mouseMoveEvent(self, a0):
        if self._drawing_shadow:
            self._shadow_end = a0.pos()
            self.update()

    def mouseReleaseEvent(self, a0):
        if self._drawing_shadow and self._shadow_start is not None and self._shadow_end is not None and a0.button() == Qt.LeftButton:
            if not hasattr(self, 'last_paint_params') or not self.last_paint_params:
                return
            params = self.last_paint_params
            scale = params.get('scale')
            if not scale or scale == 0:
                return

            start = self._shadow_start
            end = self._shadow_end
            
            center_px = ((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
            radius_px = ((start.x() - end.x())**2 + (start.y() - end.y())**2)**0.5 / 2

            center_x, center_y = self.pixel_to_world(
                center_px[0], center_px[1],
                params['px'], params['py'], params['pw'], params['ph'], scale
            )
            radius_world = radius_px / scale

            self.shadow_regions.append({'center': (center_x, center_y), 'radius': radius_world})
            
            self._drawing_shadow = False
            self._shadow_start = None
            self._shadow_end = None
            self.update()

    def paintEvent(self, a0):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        
        # draw background and calculate transform parameters
        if self.map_pixmap:
            scaled_map = self.map_pixmap.scaled(w, h, Qt.KeepAspectRatio)
            pw, ph = scaled_map.width(), scaled_map.height()
            px = (w - pw) // 2
            py = (h - ph) // 2
            painter.drawPixmap(px, py, scaled_map)

            if self.map_world_w > 0 and self.map_world_h > 0:
                scale_x = pw / self.map_world_w
                scale_y = ph / self.map_world_h
                scale = min(scale_x, scale_y)
                self.last_paint_params = {'px': px, 'py': py, 'pw': pw, 'ph': ph, 'scale': scale}

                # Draw stored shadow regions (world coordinates)
                painter.setPen(Qt.NoPen)
                shadow_color = QColor(255, 0, 0, 80)
                painter.setBrush(shadow_color)
                for region in self.shadow_regions:
                    center_x, center_y = region['center']
                    radius_world = region['radius']
                    cx_px, cy_px = self.world_to_pixel(center_x, center_y, px, py, pw, ph, scale)
                    r_px = radius_world * scale
                    painter.drawEllipse(int(cx_px - r_px), int(cy_px - r_px), int(2 * r_px), int(2 * r_px))

                # Draw other shapes (world coordinates)
                font = painter.font()
                font.setPointSize(1)
                font_metrics = QFontMetrics(font)
                for s in self.shapes:
                    px_, py_ = self.world_to_pixel(s['x'], s['y'], px, py, pw, ph, scale)
                    painter.setBrush(QColor(s['color']))
                    painter.setPen(Qt.NoPen)
                    if s['shape'] == 'circle':
                        painter.drawEllipse(int(px_ - 10), int(py_ - 10), 20, 20)
                    elif s['shape'] == 'rect':
                        painter.drawRect(int(px_ - 5), int(py_ - 5), 20, 20)
                    if s['label']:
                        painter.setPen(Qt.black)
                        painter.drawText(int(px_ + 12), int(py_ - font_metrics.height() // 2), str(s['label']))

        # Draw temporary shadow while drawing (pixel coordinates)
        if self._drawing_shadow and self._shadow_start is not None and self._shadow_end is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 0, 0, 80))
            start = self._shadow_start
            end = self._shadow_end
            center = ((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
            radius = int(((start.x() - end.x()) ** 2 + (start.y() - end.y()) ** 2) ** 0.5 / 2)
            painter.drawEllipse(center[0] - radius, center[1] - radius, 2 * radius, 2 * radius)

    def clear_shadow_regions(self):
        self.shadow_regions = []
        self.update()
