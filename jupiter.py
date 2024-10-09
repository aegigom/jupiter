import os
import time
import can
import threading
from vcgencmd import Vcgencmd
from functions import initialize_canbus_connection
from tesla import Buffer, Dashboard, Autopilot, Reboot, monitoring_addrs, MapLampControl

class Jupiter(threading.Thread):
    def __init__(self, dash):
        super().__init__()
        self.jupiter_online = True
        self.dash = dash
        self.vcgm = Vcgencmd()

    def run(self):
        if not self.jupiter_online:
            return False
        # CAN Bus Device 초기화
        initialize_canbus_connection()
        can_bus = can.interface.Bus(channel='can0', interface='socketcan')
        bus_connected = 0
        bus_error = 0
        self.dash.bus_error_count = 0
        last_recv_time = time.time()
        bus = 0  # 라즈베리파이는 항상 0, panda는 다채널이므로 수신하면서 확인

        # 핵심 기능 로딩
        BUFFER = Buffer()

        #  부가 기능 로딩
        AP = Autopilot(BUFFER, self.dash,
                       sender=can_bus,
                       device='raspi',
                       mars_mode=0)

        MAPLAMP = MapLampControl(BUFFER, self.dash, device='raspi')

        #REBOOT = Reboot(self.dash)
        REBOOT = Reboot()

        while True:
            current_time = time.time()
            self.dash.current_time = current_time
            if (bus_connected == 1):
                if self.dash.bus_error_count > 5:
                    print('Bus Error Count Over, reboot')
                    os.system('sudo reboot')
                if bus_error == 1:
                    self.dash.bus_error_count += 1
                    print(f'Bus Error, {self.dash.bus_error_count}')
                    initialize_canbus_connection()
                    can_bus = can.interface.Bus(channel='can0', interface='socketcan')
                    bus_error = 0
                else:
                    if (current_time - last_recv_time >= 5):
                        print('bus error counted')
                        bus_error = 1
                        self.dash.bus_error_count += 1
                        last_recv_time = time.time()
            elif (bus_connected == 0) and (current_time - last_recv_time >= 10):
                print('Waiting until CAN Bus Connecting...',
                      time.strftime('%m/%d %H:%M:%S', time.localtime(last_recv_time)))
                initialize_canbus_connection()
                last_recv_time = time.time()

            ###################################################
            ############## 파트1. 메시지를 읽는 영역 ##############
            ###################################################
            try:
                recv_message = can_bus.recv(1)
            except Exception as e:
                print('메시지 수신 실패\n', e)
                bus_error = 1
                recv_message = None
                continue

            if recv_message is not None:
                last_recv_time = time.time()
                address = recv_message.arbitration_id
                signal = recv_message.data
                BUFFER.write_can_buffer(bus, address, signal)

                # 여러 로직에 활용하기 위한 차량 상태값 모니터링
                dash_item = monitoring_addrs.get(address)
                if dash_item is not None:
                    self.dash.update(dash_item, signal)
                self.dash.last_update = current_time

                # 1초에 한번 전송되는 차량 시각 정보 수신
                if address == 0x528:
                    TICK = True
                    bus_connected = 1
                    self.dash.update('UnixTime', signal)
                else:
                    TICK = False

                # 매 1초마다 실행할 액션 지정
                if TICK:
                    self.dash.device_temp = self.vcgm.measure_temp()

                    # for bid, val in self.dash.beacon.items():
                    #     print(f'{bid} value is now {val}')
                    ##### Mars Mode ######
                    AP.tick()

                # 실시간 패킷 인식 및 변조
                if address == 0x1f9:
                    ##### 문열기 #####
                    signal = MAPLAMP.check(bus, address, signal)
                if address == 0x273:
                    ##### 미러 폴딩 기능 동작 #####
                    signal = MAPLAMP.check(bus, address, signal)
                if address == 0x3e2:
                    ##### 맵등 버튼을 길게 눌러 기능을 제공하기 위해, 눌림 상태를 점검 #####
                    signal = MAPLAMP.check(bus, address, signal)
                if address == 0x3c2:
                    signal = MAPLAMP.check(bus, address, signal)
                    ##### 재부팅 명령 모니터링 ###
                    signal = REBOOT.check(bus, address, signal)
                if address == 0x118:
                    ##### 기어 스토크 조작 인식 - 오토파일럿 동작 여부 확인 #####
                    signal = AP.check(bus, address, signal)

            ###################################################
            ############ 파트2. 메시지를 보내는 영역 ##############
            ###################################################

            try:
                    for _, address, signal in BUFFER.message_buffer:
                        can_bus.send(can.Message(arbitration_id=address,
                                                 channel='can0',
                                                 data=bytearray(signal),
                                                 dlc=len(bytearray(signal)),
                                                 is_extended_id=False))
            except Exception as e:
                print("메시지 발신 실패, Can Bus 리셋 시도 \n", e)
                bus_error = 1

            BUFFER.flush_message_buffer()

    def stop(self):
        self.jupiter_online = False


def main():
    DASH = Dashboard()
    J = Jupiter(DASH)
    J.start()

if __name__ == '__main__':
    main()
