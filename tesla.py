import os
import time
import random
from packet_functions import get_value, modify_packet_value, make_new_packet

# 로그파일로 남길 메모리 주소
logging_address = ['0x108', '0x118', '0x129', '0x132', '0x186', '0x1d5', '0x1d8', '0x201', '0x20c',
                   '0x229', '0x238', '0x243', '0x249', '0x257', '0x25a', '0x261', '0x266', '0x273',
                   '0x282', '0x292', '0x293', '0x2a7', '0x2b3', '0x2d3', '0x2e1', '0x2e5', '0x2f1',
                   '0x2f3', '0x312', '0x315', '0x318', '0x321', '0x32c', '0x332', '0x334', '0x33a',
                   '0x352', '0x353', '0x373', '0x376', '0x383', '0x39d', '0x3b6', '0x3d2', '0x3d8',
                   '0x3e2', '0x3e3', '0x3f2', '0x3f5', '0x3fd', '0x401', '0x4f', '0x528', '0x7aa',
                   '0x7ff']

# multiplexer 적용 패킷인 경우, multiplexer 개수 정보 추가
mux_address = {'0x282': 2, '0x352': 2, '0x3fd': 3, '0x332': 2, '0x261': 2, '0x243': 3, '0x7ff': 8,
               '0x2e1': 3, '0x201': 3, '0x7aa': 4, '0x2b3': 4, '0x3f2': 4, '0x32c': 8, '0x401': 8}

command = {
    'empty': bytes.fromhex('2955000000000000'),
    'volume_down': bytes.fromhex('2955010000000000'),
    'volume_up': bytes.fromhex('29553f0000000000'),
    'speed_down': bytes.fromhex('2955003f00000000'),
    'speed_up': bytes.fromhex('2955000100000000'),
    'distance_far': bytes.fromhex('2956000000000000'),
    'distance_near': bytes.fromhex('2959000000000000'),
    'media_back': bytes.fromhex('2995000000000000'),
    'door_open_LF': bytes.fromhex('6000000000000000'),
    'door_open_RF': bytes.fromhex('0003000000000000'),
    'door_open_LR': bytes.fromhex('0018000000000000'),
    'door_open_RR': bytes.fromhex('00c0000000000000'),
}

# 상시 모니터링 할 주요 차량정보 접근 주소
monitoring_addrs = {0x102: 'VCLEFT_doorStatus',
                    0x103: 'VCRIGHT_doorStatus',
                    0x118: 'DriveSystemStatus',
                    0x257: 'DIspeed',
                    0x528: 'UnixTime',
                    }

class Reboot:
    # def __init__(self, dash):
    def __init__(self):
        # self.dash = dash
        self.last_pressed = 0
        self.requested = 0

    def check(self, bus, address, byte_data):
        if (bus == 0) and (address == 0x3c2):
            mux = get_value(byte_data, 0, 2)
            if mux == 1:
                left_clicked = get_value(byte_data, 5, 2)
                right_clicked = get_value(byte_data, 12, 2)
                if left_clicked == 2 and right_clicked == 2:
                    if self.requested == 0:
                        self.requested = 1
                        print('Reboot Request counted')
                        self.last_pressed = time.time()
                    else:
                        if time.time() - self.last_pressed >= 1:
                            print('Reboot Request')
                            os.system('sudo reboot')
                else:
                    self.requested = 0


class Buffer:
    def __init__(self):
        self.logging_address = [int(x, 16) for x in logging_address]
        self.mux_address = mux_address
        self.can_buffer = {}
        self.message_buffer = []
        self.initial_can_buffer()

    def initial_can_buffer(self):
        self.can_buffer = {0: {x: {0: None} for x in self.logging_address}}
        for m_address, byte in self.mux_address.items():
            for i in range(2 ** byte):
                self.can_buffer[0][int(m_address, 16)][i] = None

    def flush_message_buffer(self):
        self.message_buffer = []

    def write_can_buffer(self, bus: int, address: int, signal: bytes):
        if hex(address) in self.mux_address.keys():
            mux = signal[0] & (2 ** self.mux_address[hex(address)] - 1)
        else:
            mux = 0
        if self.can_buffer[bus].get(address):
            self.can_buffer[bus][address][mux] = signal

    def write_message_buffer(self, bus, address, signal):
        self.message_buffer.append([bus, address, signal])


class Dashboard:
    def __init__(self):
        self.bus_error_cout = 0
        self.current_time = 0
        self.last_update = 0
        self.unix_time = 0
        self.parked = 1
        self.ui_speed = 0
        self.device_temp = 0
        self.mars_mode = 0
        self.gear = 0
        self.mirror_folded = [0, 0]  # folded 1, unfolded 0

    def update(self, name, signal):
        if name == 'UnixTime':
            self.unix_time = int.from_bytes(signal, byteorder='big')
        elif name == 'DriveSystemStatus':
            self.gear = get_value(signal, 21, 3)
        elif name == 'DIspeed':
            self.ui_speed = max(0, get_value(signal, 24, 9))
        elif name == 'VCLEFT_doorStatus':
            state = get_value(signal, 52, 3)
            if state in [2, 4]:
                self.mirror_folded[0] = 0
            elif state in [1, 3]:
                self.mirror_folded[0] = 1
        elif name == 'VCRIGHT_doorStatus':
            state = get_value(signal, 52, 3)
            if state in [2, 4]:
                self.mirror_folded[1] = 0
            elif state in [1, 3]:
                self.mirror_folded[1] = 1


class MapLampControl:
    def __init__(self, buffer, dash, device='raspi'):
        self.buffer = buffer
        self.dash = dash
        self.device = device
        self.left_map_light_pressed = 0
        self.right_map_light_pressed = 0
        self.left_steer_joy_pressed = 0
        self.left_map_light_pressed_time = 0
        self.right_map_light_pressed_time = 0
        self.left_steer_joy_pressed_time = 0
        self.left_map_light_release_time = 0
        self.right_map_light_release_time = 0
        self.left_steer_joy_release_time = 0
        self.ret = None

        # 원래 CAN 메시지에 타이밍 맞춰 보내기 위해 사용하는 변수
        self.mirror_request = 0  # 0 중립, 1 접기 2 펴기
        self.door_open_request = None

    def check(self, bus, address, byte_data):
        if (bus == 0) and (address == 0x3e2):
            # Check Left Map Light Long Pressed
            if get_value(byte_data, 14, 1) == 1:
                if self.left_map_light_pressed == 0:
                    self.left_map_light_pressed_time = time.time()
                    self.left_map_light_pressed = 1
                if self.left_map_light_pressed_time != 0:
                    if time.time() - self.left_map_light_pressed_time >= 1:
                        # self.left_map_light_switch_long_pressed()
                        self.mirror_fold()
                        self.left_map_light_pressed_time = 0
                    if self.left_map_light_pressed_time - self.left_map_light_release_time <= 0.5:
                        # self.left_map_light_switch_Dbl_pressed()
                        self.open_door('LR')
                        self.left_map_light_pressed_time = 0
            else:
                self.left_map_light_pressed = 0
                self.left_map_light_release_time = self.left_map_light_pressed_time
                self.left_map_light_pressed_time = 0

            # Check Right Map Light Long Pressed
            if get_value(byte_data, 15, 1) == 1:
                if self.right_map_light_pressed == 0:
                    self.right_map_light_pressed_time = time.time()
                    self.right_map_light_pressed = 1
                if self.right_map_light_pressed_time != 0:
                    if time.time() - self.right_map_light_pressed_time >= 1:
                        # self.right_map_light_switch_long_pressed()
                        self.open_door('RF')
                        self.right_map_light_pressed_time = 0
                    if self.right_map_light_pressed_time - self.right_map_light_release_time <= 0.75:
                        # self.Right_map_light_switch_Dbl_pressed()
                        self.open_door('RR')
                        self.right_map_light_pressed_time = 0
            else:
                self.right_map_light_pressed = 0
                self.right_map_light_release_time = self.right_map_light_pressed_time
                self.right_map_light_pressed_time = 0

        if (bus == 0) and (address == 0x3c2):
            # Check Left Map Light Long Pressed
            if byte_data[0] == 0x49 and byte_data[1] == 0x55:
                if self.left_steer_joy_pressed == 0:
                    self.left_steer_joy_pressed_time = time.time()
                    self.left_steer_joy_pressed = 1
                if self.left_steer_joy_pressed_time != 0:
                    if self.left_steer_joy_pressed_time - self.left_steer_joy_release_time <= 0.75:
                        # self.left_map_light_switch_Dbl_pressed()
                        self.nag_mode_toggle()
                        self.left_steer_joy_pressed_time = 0
            else:
                self.left_steer_joy_pressed = 0
                self.left_steer_joy_release_time = self.left_steer_joy_pressed_time
                self.left_steer_joy_pressed_time = 0

        if (bus == 0) and (address == 0x273):
            if self.mirror_request in [1, 2]:
                ret = modify_packet_value(byte_data, 24, 2, self.mirror_request)
                self.buffer.write_message_buffer(0, 0x273, ret)
                self.mirror_request = 0
                return ret

        # Door Open Action
        if (bus == 0) and (address == 0x1f9):
            if self.door_open_request is None:
                pass
            else:
                self.ret = None
                door_loc = str(self.door_open_request)
                if door_loc == 'LF':
                    self.ret = bytes.fromhex('6000000000000000')
                elif door_loc == 'RF':
                    self.ret = bytes.fromhex('0003000000000000')
                elif door_loc == 'LR':
                    self.ret = bytes.fromhex('0018000000000000')
                elif door_loc == 'RR':
                    self.ret = bytes.fromhex('00c0000000000000')

                if self.ret:
                    self.buffer.write_message_buffer(0, 0x1f9, self.ret)
                self.door_open_request = None
                return self.ret
        return byte_data

    # Action 함수들
    def open_door(self, loc):
        if self.dash.ui_speed == 0:
            door_positions = ('LF', 'RF', 'LR', 'RR')
            if loc in door_positions:
                print(loc)
                self.door_open_request = loc

    def mirror_fold(self):
        if self.dash.mirror_folded[0] == 1 or self.dash.mirror_folded[1] == 1:
            self.mirror_request = 2
        else:
            self.mirror_request = 1

    def nag_mode_toggle(self):
        self.dash.mars_mode ^= 1

class Autopilot:
    def __init__(self, buffer, dash, sender=None, device='raspi', mars_mode=0):
        self.timer = 0
        self.buffer = buffer
        self.dash = dash
        self.mars_mode = mars_mode if mars_mode is not None else 0
        self.dash.mars_mode = self.mars_mode
        self.parked = self.dash.parked
        self.repeatNum = 7
        self.last_p_ts = 0
        self.last_d_ts = 0

        if sender is not None:
            self.sender = sender
            if device == 'raspi':
                self.device = 'raspi'
            else:
                self.device = None
                print('device error. panda and raspi allowed')
                raise

    def tick(self):
        # Dynamic Following Distance 제어를 위해 평균 속도를 산출 및 제어 (최근 3초 평균 속도 기준으로 제어)
        self.mars_mode = self.dash.mars_mode

        # Mars Mode from Spleck's github (https://github.com/spleck/panda)
        # 운전 중 스티어링 휠을 잡고 정확히 조향하는 것은 운전자의 의무입니다.
        # 미국 생산 차량에서만 다이얼을 이용한 NAG 제거가 유효하며, 중국 생산차량은 적용되지 않습니다.
        if self.mars_mode:
            self.timer += 1
            if self.timer == self.repeatNum-2:
                print('Left Scroll Wheel Down')
                self.buffer.write_message_buffer(0, 0x3c2, command['volume_down'])
            elif self.timer == self.repeatNum-1:
                print('Left Scroll Wheel Up')
                self.buffer.write_message_buffer(0, 0x3c2, command['volume_up'])
            if self.timer >= self.repeatNum:
                self.timer = 0
                self.repeatNum = random.randrange(20, 60)

    def disengage_autopilot(self):
        self.dash.mars_mode = 0
        self.mars_mode = 0

    def check(self, bus, address, byte_data):
        ret = byte_data
        # continuous ap 판단
        # if self.dash.gear != 4:
        #    self.disengage_autopilot()

        if (bus == 0) and (address == 0x118):
            # Check Left Map Light Long Pressed
            if byte_data[2] <= 50 or byte_data[2] >= 240:
                self.last_p_ts = time.time()
            else:
                self.last_d_ts = time.time()

            if self.parked == 0 and (self.last_p_ts > self.last_d_ts):
                    self.parked = 1
                    print("Changing to PARK mode")
                    if self.mars_mode == 1:
                        self.dash.mars_mode = 0
                        self.mars_mode = 0
                        self.dash.parked = 1
            elif self.parked == 1 and (self.last_d_ts > self.last_p_ts):
                    self.parked = 0
                    print("Changing to NON-PARK mode ")
                    if self.mars_mode == 0:
                        self.dash.parked = 0
                        self.parked = 0

        return ret
