import itertools
import socket
import struct


READ_HOLDING_REGISTERS = 0x03
WRITE_MULTIPLE_REGISTERS = 0x10


DEFAULT_KOLLMORGEN_TAGS = [
    {
        "nome": "MODBUS.DRVSTAT",
        "endereco": 944,
        "registradores": 2,
        "tipo": "uint32",
        "escala": 1,
        "unidade": "bits",
    },
    {
        "nome": "MODBUS.DIO",
        "endereco": 940,
        "registradores": 2,
        "tipo": "uint32",
        "escala": 1,
        "unidade": "bits",
    },
    {
        "nome": "DRV.MOTIONSTAT",
        "endereco": 268,
        "registradores": 2,
        "tipo": "uint32",
        "escala": 1,
        "unidade": "bits",
    },
    {
        "nome": "VL.FB",
        "endereco": 856,
        "registradores": 2,
        "tipo": "int32",
        "escala": 1,
        "unidade": "counts/s",
    },
    {
        "nome": "MODBUS.PSCALE",
        "endereco": 978,
        "registradores": 2,
        "tipo": "uint16",
        "escala": 1,
        "unidade": "bits",
    },
    {
        "nome": "MOTOR.TEMP",
        "endereco": 514,
        "registradores": 2,
        "tipo": "uint32",
        "escala": 0.001,
        "unidade": "C",
    },
    {
        "nome": "IL.FB",
        "endereco": 432,
        "registradores": 2,
        "tipo": "int32",
        "escala": 1,
        "unidade": "mA",
    },
    {
        "nome": "VBUS.VALUE",
        "endereco": 806,
        "registradores": 2,
        "tipo": "uint32",
        "escala": 0.001,
        "unidade": "V",
    },
    {
        "nome": "DRV.FAULT1",
        "endereco": 954,
        "registradores": 2,
        "tipo": "uint16",
        "escala": 1,
        "unidade": "codigo",
    },
    {
        "nome": "DRV.FAULT2",
        "endereco": 956,
        "registradores": 2,
        "tipo": "uint16",
        "escala": 1,
        "unidade": "codigo",
    },
    {
        "nome": "DRV.FAULT3",
        "endereco": 958,
        "registradores": 2,
        "tipo": "uint16",
        "escala": 1,
        "unidade": "codigo",
    },
]


class ModbusError(Exception):
    pass


class KollmorgenModbusClient:
    def __init__(self, ip, port=502, unit_id=1, timeout=3):
        self.ip = ip
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.timeout = float(timeout)
        self._sock = None
        self._transactions = itertools.count(1)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def connect(self):
        if self._sock:
            return

        self._sock = socket.create_connection(
            (self.ip, self.port),
            timeout=self.timeout,
        )
        self._sock.settimeout(self.timeout)

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def read_holding_registers(self, address, quantity):
        if quantity not in (1, 2, 4, 8, 16):
            raise ModbusError("Quantidade de registradores invalida")

        pdu = struct.pack(
            ">BHH",
            READ_HOLDING_REGISTERS,
            int(address),
            int(quantity),
        )
        response = self._request(pdu)

        function = response[0]
        if function == READ_HOLDING_REGISTERS | 0x80:
            raise ModbusError(f"Excecao Modbus {response[1]}")
        if function != READ_HOLDING_REGISTERS:
            raise ModbusError(f"Funcao Modbus inesperada {function}")

        byte_count = response[1]
        expected = int(quantity) * 2
        if byte_count != expected:
            raise ModbusError(
                f"Resposta com {byte_count} bytes, esperado {expected}"
            )

        data = response[2:]
        return list(struct.unpack(f">{quantity}H", data))

    def write_multiple_registers(self, address, registers):
        registers = [int(register) & 0xFFFF for register in registers]
        quantity = len(registers)
        if quantity == 0:
            raise ModbusError("Nenhum registrador para escrever")

        payload = struct.pack(
            ">BHHB",
            WRITE_MULTIPLE_REGISTERS,
            int(address),
            quantity,
            quantity * 2,
        )
        payload += struct.pack(f">{quantity}H", *registers)

        response = self._request(payload)
        function = response[0]
        if function == WRITE_MULTIPLE_REGISTERS | 0x80:
            raise ModbusError(f"Excecao Modbus {response[1]}")
        if function != WRITE_MULTIPLE_REGISTERS:
            raise ModbusError(f"Funcao Modbus inesperada {function}")

        written_address, written_quantity = struct.unpack(">HH", response[1:])
        return {
            "endereco": written_address,
            "registradores": written_quantity,
        }

    def _request(self, pdu):
        self.connect()

        transaction_id = next(self._transactions) & 0xFFFF
        header = struct.pack(
            ">HHHB",
            transaction_id,
            0,
            len(pdu) + 1,
            self.unit_id,
        )

        self._sock.sendall(header + pdu)

        response_header = self._recv_exact(7)
        received_transaction, protocol, length, unit_id = struct.unpack(
            ">HHHB",
            response_header,
        )

        if received_transaction != transaction_id:
            raise ModbusError("Transacao Modbus fora de sequencia")
        if protocol != 0:
            raise ModbusError("Protocolo Modbus invalido")
        if unit_id != self.unit_id:
            raise ModbusError("Unit ID Modbus inesperado")

        return self._recv_exact(length - 1)

    def _recv_exact(self, size):
        chunks = []
        remaining = size

        while remaining:
            chunk = self._sock.recv(remaining)
            if not chunk:
                raise ModbusError("Conexao encerrada pelo driver")
            chunks.append(chunk)
            remaining -= len(chunk)

        return b"".join(chunks)


def decode_registers(registers, data_type):
    registers = [int(register) & 0xFFFF for register in registers]
    data_type = (data_type or "int32").lower()

    if data_type == "raw":
        return registers

    if data_type == "uint16":
        return registers[-1]
    if data_type == "int16":
        return _to_signed(registers[-1], 16)

    if data_type in ("uint32", "int32", "float32"):
        _require_registers(registers, 2, data_type)
        raw = (registers[0] << 16) | registers[1]

        if data_type == "uint32":
            return raw
        if data_type == "int32":
            return _to_signed(raw, 32)

        return struct.unpack(">f", struct.pack(">I", raw))[0]

    if data_type in ("uint64", "int64"):
        _require_registers(registers, 4, data_type)
        raw = 0
        for register in registers[:4]:
            raw = (raw << 16) | register

        if data_type == "uint64":
            return raw

        return _to_signed(raw, 64)

    raise ModbusError(f"Tipo de dado nao suportado: {data_type}")


def decode_status_bits(parameter_name, value):
    parameter_name = (parameter_name or "").upper()

    if parameter_name == "MODBUS.DRVSTAT":
        return {
            "drive_ativo": bool(value & (1 << 0)),
            "sto": bool(value & (1 << 1)),
            "limite_hw_positivo": bool(value & (1 << 2)),
            "limite_hw_negativo": bool(value & (1 << 3)),
            "limite_sw_positivo": bool(value & (1 << 4)),
            "limite_sw_negativo": bool(value & (1 << 5)),
        }

    if parameter_name == "MODBUS.DIO":
        bits = {}

        for bit in range(7):
            bits[f"din{bit + 1}"] = bool(value & (1 << bit))

        bits["dout1"] = bool(value & (1 << 16))
        bits["dout2"] = bool(value & (1 << 17))
        return bits

    return None


def _require_registers(registers, expected, data_type):
    if len(registers) < expected:
        raise ModbusError(
            f"{data_type} precisa de {expected} registradores"
        )


def _to_signed(value, bits):
    sign_bit = 1 << (bits - 1)
    return (value ^ sign_bit) - sign_bit
