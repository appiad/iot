from bluepy.btle import Scanner, DefaultDelegate

class ScanDelegate(DefaultDelegate):
    def __init__(self, R1List, R2List):
        DefaultDelegate.__init__(self)
        self.R1List = R1List
        self.R2List = R2List

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if isNewDev or isNewData:
            if dev.addr == u'fb:13:5e:5d:d1:d5':
                self.R1List.append(dev.rssi)
            elif dev.addr == u'ec:b6:d0:1e:0c:5e':
                self.R2List.append(dev.rssi)

if __name__ == "__main__":
    Room1_values = []
    Room2_values = []
    scanner = Scanner().withDelegate(ScanDelegate(Room1_values, Room2_values))
    for i in range(15):
        devices = scanner.scan(10)
    print(len(Room1_values))
    print(len(Room2_values))
    # assert(len(Room1_values) == 15)
    # assert(len(Room2_values) == 15)

    print("The Average Room 1 Beacon RSSI At This Location is %i" % (sum(Room1_values) / len(Room1_values)))
    print("The Average Room 2 Beacon RSSI At This Location is %i" % (sum(Room2_values) / len(Room2_values)))
