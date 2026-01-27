#!/usr/bin/env python
"""
串口双向桥接控制器 - 带完整协议日志
- COM7 (9600): 上位机端
- COM13 (9600): 电机控制器端（3个电机）
- 双向透明转发，所有收发数据记录到日志文件
"""

import serial
import sys
import time
import os
from datetime import datetime

class SerialBridge:
    def __init__(self, port1='COM7', port2='COM13', baudrate=9600):
        self.port1 = port1  # 上位机端
        self.port2 = port2  # 电机端
        self.baudrate = baudrate
        
        self.serial1 = None
        self.serial2 = None
        self.running = False
        
        # 日志文件
        log_dir = os.path.dirname(os.path.abspath(__file__))
        log_filename = datetime.now().strftime('serial_log_%Y%m%d_%H%M%S.txt')
        self.log_path = os.path.join(log_dir, log_filename)
        self.log_file = None
        
        # 统计
        self.bytes_1_to_2 = 0
        self.bytes_2_to_1 = 0
        self.packets_1_to_2 = 0
        self.packets_2_to_1 = 0
        
    def log(self, direction, data_raw, data_text=None):
        """记录日志到文件和控制台"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # 格式化十六进制
        hex_str = ' '.join(f'{b:02X}' for b in data_raw)
        
        # 尝试解码文本
        if data_text is None:
            try:
                data_text = data_raw.decode('utf-8').replace('\r', '\\r').replace('\n', '\\n')
            except:
                data_text = "[binary]"
        
        # 日志行
        log_line = f"[{timestamp}] {direction} | LEN:{len(data_raw):3d} | HEX: {hex_str} | TEXT: {data_text}"
        
        # 输出到控制台
        print(log_line)
        
        # 写入日志文件
        if self.log_file:
            self.log_file.write(log_line + '\n')
            self.log_file.flush()
    
    def connect(self):
        """连接两个串口"""
        try:
            # 打开日志文件
            self.log_file = open(self.log_path, 'w', encoding='utf-8')
            print(f"[OK] 日志文件: {self.log_path}")
            
            # 写日志头
            self.log_file.write(f"串口桥接日志\n")
            self.log_file.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.log_file.write(f"端口1: {self.port1} @ {self.baudrate}\n")
            self.log_file.write(f"端口2: {self.port2} @ {self.baudrate}\n")
            self.log_file.write("=" * 120 + "\n")
            self.log_file.flush()
            
            # 串口1 (COM7 - 上位机)
            self.serial1 = serial.Serial(
                port=self.port1,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.01
            )
            print(f"[OK] 已连接 {self.port1} @ {self.baudrate} (上位机端)")
            
            # 串口2 (COM13 - 电机)
            self.serial2 = serial.Serial(
                port=self.port2,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.01
            )
            print(f"[OK] 已连接 {self.port2} @ {self.baudrate} (电机端)")
            
            return True
            
        except serial.SerialException as e:
            print(f"[ERROR] 串口连接失败: {e}")
            return False
        except Exception as e:
            print(f"[ERROR] 错误: {e}")
            return False
    
    def disconnect(self):
        """断开串口"""
        if self.serial1 and self.serial1.is_open:
            self.serial1.close()
        if self.serial2 and self.serial2.is_open:
            self.serial2.close()
        if self.log_file:
            # 写入统计信息
            self.log_file.write("\n" + "=" * 120 + "\n")
            self.log_file.write(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.log_file.write(f"统计:\n")
            self.log_file.write(f"  {self.port1} -> {self.port2}: {self.packets_1_to_2} 包, {self.bytes_1_to_2} 字节\n")
            self.log_file.write(f"  {self.port2} -> {self.port1}: {self.packets_2_to_1} 包, {self.bytes_2_to_1} 字节\n")
            self.log_file.close()
        print("[INFO] 串口已断开")
    
    def run(self):
        """主循环 - 双向转发"""
        if not self.connect():
            return 1
            
        self.running = True
        print("\n" + "=" * 80)
        print("串口双向桥接器已启动")
        print(f"  {self.port1} <---> {self.port2}  @ {self.baudrate} baud")
        print(f"  日志文件: {self.log_path}")
        print("按 Ctrl+C 停止")
        print("=" * 80 + "\n")
        
        try:
            while self.running:
                # 方向1: COM7 -> COM13 (上位机 -> 电机)
                if self.serial1.in_waiting > 0:
                    data = self.serial1.read(self.serial1.in_waiting)
                    if data:
                        self.serial2.write(data)
                        self.bytes_1_to_2 += len(data)
                        self.packets_1_to_2 += 1
                        self.log(f"{self.port1} -> {self.port2}", data)
                
                # 方向2: COM13 -> COM7 (电机 -> 上位机)
                if self.serial2.in_waiting > 0:
                    data = self.serial2.read(self.serial2.in_waiting)
                    if data:
                        self.serial1.write(data)
                        self.bytes_2_to_1 += len(data)
                        self.packets_2_to_1 += 1
                        self.log(f"{self.port2} -> {self.port1}", data)
                
                time.sleep(0.001)  # 1ms 循环延时
                
        except KeyboardInterrupt:
            print("\n[INFO] 正在停止...")
            
        finally:
            self.running = False
            self.disconnect()
            
        # 打印统计
        print("\n" + "=" * 80)
        print("统计信息:")
        print(f"  {self.port1} -> {self.port2}: {self.packets_1_to_2} 包, {self.bytes_1_to_2} 字节")
        print(f"  {self.port2} -> {self.port1}: {self.packets_2_to_1} 包, {self.bytes_2_to_1} 字节")
        print(f"  日志已保存: {self.log_path}")
        print("=" * 80)
            
        return 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='串口双向桥接控制器')
    parser.add_argument('--port1', default='COM7', help='端口1 - 上位机端 (默认: COM7)')
    parser.add_argument('--port2', default='COM13', help='端口2 - 电机端 (默认: COM13)')
    parser.add_argument('-b', '--baudrate', type=int, default=9600, help='波特率 (默认: 9600)')
    
    args = parser.parse_args()
    
    bridge = SerialBridge(
        port1=args.port1,
        port2=args.port2,
        baudrate=args.baudrate
    )
    
    return bridge.run()


if __name__ == '__main__':
    sys.exit(main())
