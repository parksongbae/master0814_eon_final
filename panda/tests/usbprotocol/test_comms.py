import random
import unittest

from panda import Panda, DLC_TO_LEN, USBPACKET_MAX_SIZE, pack_can_buffer, unpack_can_buffer
from panda.tests.libpanda import libpanda_py

lpp = libpanda_py.libpanda

CHUNK_SIZE = USBPACKET_MAX_SIZE
TX_QUEUES = (lpp.tx1_q, lpp.tx2_q, lpp.tx3_q, lpp.txgmlan_q)


def unpackage_can_msg(pkt):
  dat_len = DLC_TO_LEN[pkt[0].data_len_code]
  dat = bytes(pkt[0].data[0:dat_len])
  return pkt[0].addr, 0, dat, pkt[0].bus


def random_can_messages(n, bus=None):
  msgs = []
  for _ in range(n):
    if bus is None:
      bus = random.randint(0, 3)
    address = random.randint(1, (1 << 29) - 1)
    data = bytes([random.getrandbits(8) for _ in range(DLC_TO_LEN[random.randrange(0, len(DLC_TO_LEN))])])
    msgs.append((address, 0, data, bus))
  return msgs


class TestPandaComms(unittest.TestCase):
  def test_tx_queues(self):
    for bus in range(4):
      message = (0x100, 0, b"test", bus)

      can_pkt_tx = libpanda_py.make_CANPacket(message[0], message[3], message[2])
      can_pkt_rx = libpanda_py.ffi.new('CANPacket_t *')

      assert lpp.can_push(TX_QUEUES[bus], can_pkt_tx), "CAN push failed"
      assert lpp.can_pop(TX_QUEUES[bus], can_pkt_rx), "CAN pop failed"

      assert unpackage_can_msg(can_pkt_rx) == message

  def test_can_send_usb(self):
    lpp.set_safety_hooks(Panda.SAFETY_ALLOUTPUT, 0)

    for bus in range(3):
      with self.subTest(bus=bus):
        for _ in range(100):
          msgs = random_can_messages(200, bus=bus)
          packed = pack_can_buffer(msgs)

          # Simulate USB bulk chunks
          for buf in packed:
            for i in range(0, len(buf), CHUNK_SIZE):
              chunk_len = min(CHUNK_SIZE, len(buf) - i)
              lpp.comms_can_write(buf[i:i+chunk_len], chunk_len)

          # Check that they ended up in the right buffers
          queue_msgs = []
          pkt = libpanda_py.ffi.new('CANPacket_t *')
          while lpp.can_pop(TX_QUEUES[bus], pkt):
            queue_msgs.append(unpackage_can_msg(pkt))

          self.assertEqual(len(queue_msgs), len(msgs))
          self.assertEqual(queue_msgs, msgs)

  def test_can_receive_usb(self):
    msgs = random_can_messages(50000)
    packets = [libpanda_py.make_CANPacket(m[0], m[3], m[2]) for m in msgs]

    rx_msgs = []
    while len(packets) > 0:
      # Push into queue
      while lpp.can_slots_empty(lpp.rx_q) > 0 and len(packets) > 0:
        lpp.can_push(lpp.rx_q, packets.pop(0))

      # Simulate USB bulk IN chunks
      MAX_TRANSFER_SIZE = 16384
      dat = libpanda_py.ffi.new(f"uint8_t[{CHUNK_SIZE}]")
      while True:
        buf = b""
        while len(buf) < MAX_TRANSFER_SIZE:
          max_size = min(CHUNK_SIZE, MAX_TRANSFER_SIZE - len(buf))
          rx_len = lpp.comms_can_read(dat, max_size)
          buf += bytes(dat[0:rx_len])
          if rx_len < max_size:
            break

        if len(buf) == 0:
          break
        rx_msgs.extend(unpack_can_buffer(buf))

    self.assertEqual(len(rx_msgs), len(msgs))
    self.assertEqual(rx_msgs, msgs)


if __name__ == "__main__":
  unittest.main()