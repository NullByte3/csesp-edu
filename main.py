import pymem
import pymem.process
import requests
import time
import math
import sys
import win32api
import win32gui
import win32con
from threading import Thread
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsView, QGraphicsScene
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPen, QColor, QFont, QPainter

class ESPSignals(QObject):
    toggle_signal = Signal()

class ESPOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.x, self.y, self.width, self.height = get_window_info()
        self.esp_active = True
        self.signals = ESPSignals()
        self.signals.toggle_signal.connect(self._toggle_esp)
        self.setGeometry(self.x, self.y, self.width, self.height)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setup_transparency()
        
        self.scene = QGraphicsScene(0, 0, self.width, self.height, self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setGeometry(0, 0, self.width, self.height)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet("background: transparent;")
        self.view.setFrameShape(QGraphicsView.NoFrame)
        self.view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.view.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_esp)
        self.timer.start(1)
        
        # Initialize memory
        self.pm = pymem.Pymem("cs2.exe")
        self.client = pymem.process.module_from_name(self.pm.process_handle, "client.dll").lpBaseOfDll
        self.offsets, self.client_dll = get_offsets()
        
    def setup_transparency(self):
        hwnd = int(self.winId())
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, 
                             win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) | 
                             win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
    
    def update_esp(self):
        if self.esp_active:
            # Update window position
            new_x, new_y, new_width, new_height = get_window_info()
            if (new_x != self.x or new_y != self.y or
                new_width != self.width or new_height != self.height):
                self.x, self.y = new_x, new_y
                self.width, self.height = new_width, new_height
                self.setGeometry(self.x, self.y, self.width, self.height)
                self.view.setGeometry(0, 0, self.width, self.height)
                self.scene.setSceneRect(-self.width/2, -self.height/2, self.width, self.height)
            
            self.scene.clear()
            try:
                draw_esp(self.scene, self.pm, self.client, self.offsets, self.client_dll, self.width, self.height)
            except Exception as e:
                pass

    def toggle_esp(self):
        # This can be called from any thread
        self.signals.toggle_signal.emit()
        
    def _toggle_esp(self):
        # This runs in the main Qt thread
        self.esp_active = not self.esp_active
        if self.esp_active:
            self.show()
            self.timer.start(1)
            print("ESP enabled")
        else:
            self.scene.clear()
            self.timer.stop()
            self.hide()
            print("ESP disabled")

def get_offsets():
    offsets = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json()
    client_dll = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()
    return offsets, client_dll

def get_window_info():
    hwnd = win32gui.FindWindow(None, "Counter-Strike 2")
    if hwnd:
        rect = win32gui.GetWindowRect(hwnd)
        # For fullscreen windowed, use the full window dimensions
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        return rect[0], rect[1], width, height
    return 0, 0, 1920, 1080

def w2s(matrix, x, y, z, width, height):
    w = matrix[12] * x + matrix[13] * y + matrix[14] * z + matrix[15]
    if w < 0.001:
        return [-1, -1]
    
    screen_x = matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3]
    screen_y = matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7]
    
    screen_x = (width / 2) + (width / 2) * screen_x / w
    screen_y = (height / 2) - (height / 2) * screen_y / w
    
    return [int(screen_x), int(screen_y)]

def draw_esp(scene, pm, client, offsets, client_dll, width, height):
    # Get important offsets
    dwEntityList = offsets['client.dll']['dwEntityList']
    dwLocalPlayerPawn = offsets['client.dll']['dwLocalPlayerPawn']
    dwViewMatrix = offsets['client.dll']['dwViewMatrix']
    
    # Get important client_dll fields
    m_iTeamNum = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
    m_iHealth = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']
    m_lifeState = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']
    m_pGameSceneNode = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
    m_modelState = client_dll['client.dll']['classes']['CSkeletonInstance']['fields']['m_modelState']
    m_hPlayerPawn = client_dll['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']
    
    # Get local player
    local_player = pm.read_longlong(client + dwLocalPlayerPawn)
    local_team = pm.read_int(local_player + m_iTeamNum)
    
    # Get view matrix
    view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
    
    # Get entity list
    entity_list = pm.read_longlong(client + dwEntityList)
    list_entry = pm.read_longlong(entity_list + 0x10)
    
    # Draw center indicator (1 pixel dot)
    scene.addEllipse(width/2-1, height/2-1, 2, 2, QPen(QColor(255,255,255)), QColor(255,255,255))
    
    # Draw FPS
    fps = int(1/(time.time()%1+0.001))
    fps_text = scene.addText(f"ESP | FPS: {fps}", QFont("Arial", 10))
    fps_text.setDefaultTextColor(QColor(255,255,255))
    
    # Loop through entities
    for i in range(1, 64):
        try:
            # Get entity controller
            controller = pm.read_longlong(list_entry + 0x78 * (i & 0x1FF))
            if controller == 0:
                continue
                
            # Get pawn handle
            pawn_handle = pm.read_longlong(controller + m_hPlayerPawn)
            if pawn_handle == 0:
                continue
                
            # Get pawn entry and address
            list_entry2 = pm.read_longlong(entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10)
            pawn = pm.read_longlong(list_entry2 + 0x78 * (pawn_handle & 0x1FF))
            
            # Skip if pawn is local player or invalid
            if pawn == 0 or pawn == local_player:
                continue
                
            # Get entity info
            team = pm.read_int(pawn + m_iTeamNum)
            health = pm.read_int(pawn + m_iHealth)
            state = pm.read_int(pawn + m_lifeState)
            
            # Skip teammates and dead players (enemy only ESP)
            if team == local_team or health <= 0 or state != 256:
                continue
            
            # Get bone matrix
            game_scene = pm.read_longlong(pawn + m_pGameSceneNode)
            bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)
                
            # Get head and feet positions
            head_x = pm.read_float(bone_matrix + 6 * 0x20)
            head_y = pm.read_float(bone_matrix + 6 * 0x20 + 0x4)
            head_z = pm.read_float(bone_matrix + 6 * 0x20 + 0x8) + 8
            head_pos = w2s(view_matrix, head_x, head_y, head_z, width, height)
            
            feet_z = pm.read_float(bone_matrix + 0 * 0x20 + 0x8)
            feet_pos = w2s(view_matrix, head_x, head_y, feet_z, width, height)
            
            # Skip if offscreen
            if head_pos[0] <= 0 or head_pos[0] >= width or head_pos[1] <= 0:
                continue
                
            # Calculate box dimensions
            box_height = feet_pos[1] - head_pos[1]
            box_width = box_height * 0.5
            
            # Draw box
            color = QColor(255, 0, 0)  # Enemy = Red
            scene.addRect(head_pos[0] - box_width/2, head_pos[1], 
                        box_width, box_height, QPen(color, 2), Qt.NoBrush)
            
            # Draw health bar
            hp_height = box_height * (health/100)
            scene.addRect(head_pos[0] - box_width/2 - 8, head_pos[1], 
                        5, box_height, QPen(QColor(0,0,0), 1), QColor(0,0,0,128))
            scene.addRect(head_pos[0] - box_width/2 - 8, head_pos[1] + box_height - hp_height, 
                        5, hp_height, QPen(QColor(0,255,0), 1), QColor(0,255,0,200))
            
            # Get local player position
            local_scene = pm.read_longlong(local_player + m_pGameSceneNode)
            local_bone = pm.read_longlong(local_scene + m_modelState + 0x80)
            local_x = pm.read_float(local_bone + 0 * 0x20)
            local_y = pm.read_float(local_bone + 0 * 0x20 + 0x4)
            local_z = pm.read_float(local_bone + 0 * 0x20 + 0x8)
            
            # Calculate distance in meters (Source 2 uses inches as base unit)
            distance = math.sqrt((head_x - local_x)**2 + (head_y - local_y)**2 + (feet_z - local_z)**2) * 0.0254
            
            # Draw distance text
            distance_text = scene.addText(f"{distance:.1f}m", QFont("Arial", 9))
            distance_text.setDefaultTextColor(color)
            distance_text.setPos(head_pos[0] + box_width/2 + 5, head_pos[1])
            
        except Exception:
            pass

def main():
    print("Simple CS2 ESP - CLI Edition")
    print("Waiting for CS2...")
    
    # Wait for CS2 process
    while True:
        try:
            pymem.Pymem("cs2.exe")
            break
        except Exception:
            time.sleep(1)
    
    print("CS2 process found! Starting ESP overlay...")
    print("Commands:")
    print("- Press F1 to toggle ESP on/off")
    print("- Press F2 to exit")
    
    # Start overlay
    app = QApplication(sys.argv)
    esp = ESPOverlay()
    esp.show()
    
    # Key listener thread
    def key_listener():
        while True:
            if win32api.GetAsyncKeyState(win32con.VK_F1) & 0x8000:
                esp.toggle_esp()
                time.sleep(0.3)
            
            if win32api.GetAsyncKeyState(win32con.VK_F2) & 0x8000:
                print("Exiting...")
                app.quit()
                break
                
            time.sleep(0.1)
    
    # Start key listener
    Thread(target=key_listener, daemon=True).start()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
