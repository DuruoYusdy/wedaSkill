"""合成数据测试；不调用真实 MCP，不代表真实电路验证。"""
import argparse
import copy
from pathlib import Path
import unittest
import zipfile
import xml.etree.ElementTree as ET
import interface_workbook as m
import interface_controller as legacy
import diagram_identity


def fixture():
    manifest = {"analysis_id": "synthetic-demo", "title": "外围信号接口前后对照（合成演示）",
        "schematic_snapshot": "合成旧原理图数据，非真实电路", "diagram_snapshot": "合成目标方案",
        "devices": [
            {"id":"DEV-U12", "refdes":"U12", "scope":"DEMO/root", "code":"CTRL-001",
             "target_code":"CTRL-001", "action":"CHANGE", "block_id":"B12", "block_name":"主控",
             "reason":"演示SPI片选网络调整，保留SPI0和SPI1实例", "evidence":["synthetic:diff-1"]},
            {"id":"NEW-SENSOR", "scope":"DEMO/root", "code":"SENSOR-002", "action":"ADD",
             "block_id":"B40", "block_name":"新增传感器", "reason":"演示新增器件，位号和Pin待确认",
             "evidence":["synthetic:diff-2"]},
            {"id":"DEV-U30", "refdes":"U30", "scope":"DEMO/root", "code":"LEGACY-003",
             "action":"DELETE", "block_id":"B30", "block_name":"旧接口器件",
             "reason":"明确删除旧接口器件的合成需求", "evidence":["synthetic:diff-3"]}]}
    manifest['diagram'] = {'type':'block','version':4,'graph':{'type':'graph','id':0,'children':[
        {'type':'block','id':bid,'name':name,'children':[]} for bid,name in
        [('B12','主控'),('B20','存储器'),('B21','扩展设备'),('B40','新增传感器'),('B30','旧接口器件')]]}}
    rows = []
    for i, (inst, signal) in enumerate([('SPI0','SCLK'),('SPI0','MOSI'),('SPI0','MISO'),('SPI0','CS0'),('SPI1','SCLK')]):
        chain = f"U12[{i+10}] -> U20[{i+1}]" if inst == 'SPI0' else "U12[14] -> U21[1]"
        rows.append({"id":f"O{i}", "device_id":"DEV-U12", "schematic_pins":chain,
                     "source_pin_names":[f"{inst}_{'SCK' if signal == 'SCLK' else signal}"],
                     "net_name":f"{inst}_{signal}", "instance":inst, "connection_status":"VERIFIED",
                     "chain":chain, "chain_check":{"verified":True,"chain":chain,"evidence":f"synthetic:chain-{i}"},
                     "analysis":"合成工具证据，仅用于流程演示", "evidence":[f"synthetic:pin-net-{i}"],
                     "peripherals":[]})
    rows.append({"id":"OD", "device_id":"DEV-U30", "schematic_pins":"U30[2:TX] -> J3[1]",
                 "source_pin_names":["TX"],
                 "net_name":"LEGACY_TX", "connection_status":"STRUCTURED_ONLY",
                 "analysis":"删除器件原始接口留档，合成数据", "evidence":["synthetic:legacy-pin"]})
    coverage = {key:{"status":"PARTIAL","reason":"合成演示仅提供选定信号，不是完整Pin清单",
                     "evidence":["synthetic:scope"]} for key in ('DEV-U12','DEV-U30')}
    capture = {"rows":rows,"coverage":coverage}
    maps, targets = [], []
    for inst, ids, dest in [('SPI0',['O0','O1','O2','O3'],'B20'), ('SPI1',['O4'],'B21')]:
        endpoint = {"source_block_id":"B12", "source_block_name":"主控", "source_port":"SPI",
                    "destination_block_id":dest, "destination_block_name":"存储器" if dest == 'B20' else '扩展设备',
                    "destination_port":"SPI"}
        signals = {r['id']:r['net_name'].split('_')[1] for r in rows if r['id'] in ids}
        maps.append({"device_id":"DEV-U12","row_ids":ids,"instance":inst,"family":"SPI",
                     "confidence":0.9,"endpoint":endpoint,"signals":signals,
                     "reason":"合成案例已明确物理实例和目标端点", "evidence":["synthetic:block-map"]})
        targets.append({"id":f"T-{inst}", "device_id":"DEV-U12", "instance":inst, "family":"SPI",
                        "endpoint":endpoint,"signals":list(signals.values()),"evidence":["synthetic:explicit-signal-list"]})
    newep = {"source_block_id":"B12", "source_block_name":"主控", "source_port":"I2C",
             "destination_block_id":"B40", "destination_block_name":"新增传感器", "destination_port":"I2C"}
    targets.append({"id":"T-NEW","device_id":"NEW-SENSOR","instance":"I2C0","family":"I2C",
                    "endpoint":newep,"signals":["SCL","SDA"],"evidence":["synthetic:explicit-I2C"]})
    changes = [{"id":"C-CS0","device_id":"DEV-U12","original_id":"O3","action":"CHANGE",
                "reason":"片选网络拟更名，尚未执行；现有Pin保持", "evidence":["synthetic:rename-CS"],
                "fields":{"net_name":"SPI0_FLASH_CS_N","net_origin":"PROPOSED"}}]
    for sig in ['SCL','SDA']:
        changes.append({"id":"ADD-"+sig,"device_id":"NEW-SENSOR","action":"ADD","target_id":"T-NEW",
                        "pin_evidence":["synthetic:source-controller-I2C-pin"],
                        "reason":"新增I2C信号，目标Pin、电压和上拉方案待确认", "evidence":["synthetic:target-I2C"],
                        "fields":{**newep,"instance":"I2C0","family":"I2C","signal":sig,
                                  "source_pin_names":["I2C0_"+sig],
                                  "net_name":"", "net_origin":"UNRESOLVED", "mapping_confidence":None}})
    return manifest, capture, {"mappings":maps}, {"targets":targets}, {"changes":changes}


def built():
    manifest, cap, maps, targets, changes = fixture()
    s = m.new_state(manifest)
    m.capture(s,cap)
    m.freeze(s,True)
    m.map_rows(s,maps)
    m.expand(s,targets)
    m.propose(s,changes)
    return s


class Tests(unittest.TestCase):
    def test_original_immutable(self):
        s = built()
        self.assertEqual(s['original']['O3']['net_name'],'SPI0_CS0')
        self.assertEqual(next(r for r in m.modified_rows(s) if r['id']=='C-CS0')['net_origin'],'PROPOSED')
        m.validate_frozen(s)
        s['original']['O3']['net_name']='corrupted'
        with self.assertRaises(ValueError): m.validate_frozen(s)

    def test_late_capture(self):
        with self.assertRaises(ValueError): m.capture(built(),fixture()[1])

    def test_scope_and_action_required(self):
        manifest=fixture()[0]
        del manifest['devices'][0]['scope']
        with self.assertRaises(ValueError): m.new_state(manifest)

    def test_partial_requires_flag(self):
        s=m.new_state(fixture()[0]); m.capture(s,fixture()[1])
        with self.assertRaises(ValueError): m.freeze(s)

    def test_instances(self):
        s=built()
        self.assertEqual({r.get('instance') for r in m.modified_rows(s) if r['device_id']=='DEV-U12'},{'SPI0','SPI1'})
        bad=fixture()[2]; bad['mappings'][1]['instance']='SPI0'
        with self.assertRaises(ValueError): m.map_rows(s,bad)

    def test_exact_net_grouping(self):
        names=['USB_D+','USB_D-','SPI0_SCLK','SPI1_SCLK','NetA','NETA']
        pins=[legacy.normalize_pin({'pin_number':str(i),'pin_name':'DATA','net_name':name}) for i,name in enumerate(names)]
        interfaces=legacy.build_interfaces({'id':'D'},pins)
        self.assertEqual(len(interfaces),len(names))
        self.assertEqual({r['net_name'] for r in interfaces.values()},set(names))

    def test_add_has_no_original(self):
        s=m.new_state(fixture()[0]); cap=fixture()[1]
        cap['rows'][0]['device_id']='NEW-SENSOR'
        with self.assertRaises(ValueError): m.capture(s,cap)

    def test_wrong_lineage(self):
        s=built(); ch=fixture()[4]
        ch['changes'][0]['original_id']='OD'
        with self.assertRaises(ValueError): m.propose(s,ch)

    def test_schematic_origin_guard(self):
        s=built(); ch=fixture()[4]
        ch['changes'][0]['fields']['net_origin']='SCHEMATIC'
        with self.assertRaises(ValueError): m.propose(s,ch)

    def test_replace_invalidates_pins(self):
        manifest, cap, maps, targets, changes=fixture()
        manifest['devices'][0]['replacement']=True
        s=m.new_state(manifest); m.capture(s,cap); m.freeze(s,True); m.map_rows(s,maps)
        self.assertTrue(all(not r.get('schematic_pins') for r in m.modified_rows(s) if r['device_id']=='DEV-U12'))

    def test_chain_exact(self):
        s=m.new_state(fixture()[0]); cap=fixture()[1]
        cap['rows'][0]['chain_check']['chain']='different'
        with self.assertRaises(ValueError): m.capture(s,cap)

    def test_idempotence(self):
        s=built(); before=copy.deepcopy(s)
        m.propose(s,fixture()[4]); m.map_rows(s,fixture()[2]); m.expand(s,fixture()[3])
        self.assertEqual(s,before)

    def test_missing_target_members(self):
        s=built(); s['changes'].pop('ADD-SCL')
        pending=m.next_actions(s)
        self.assertTrue(any(p.get('signal')=='SCL' for p in pending))

    def test_delete_signal_retains_baseline(self):
        s=built()
        m.propose(s,{'changes':[{'id':'DELETE-O0','device_id':'DEV-U12','original_id':'O0','action':'DELETE',
                                'reason':'explicit removal','evidence':['synthetic:delete']}]})
        self.assertIn('O0',s['original'])
        self.assertFalse(any(r.get('original_id')=='O0' for r in m.modified_rows(s)))
        self.assertEqual(len(m.model(s)['devices'][0]['deleted_signals']),1)

    def test_layout(self):
        data=m.model(built())
        self.assertEqual(len(data['columns']),21)
        self.assertEqual(data['columns'][9],'网络命名')
        self.assertEqual(len(data['devices'][1]['before']),0)
        self.assertEqual(len(data['devices'][2]['after']),0)
        used=set()
        a=m.sheet_name('A'*35,used); b=m.sheet_name('A'*35,used)
        self.assertNotEqual(a,b)
        self.assertLessEqual(len(b),31)
        self.assertNotIn('/',m.sheet_name('U/12',used))

    def test_json_id_and_name(self):
        data=m.model(built())
        self.assertEqual(data['devices'][0]['block_id'],'0-B12')
        self.assertEqual(data['devices'][0]['after'][0][:2],['0-B12','主控'])
        self.assertEqual(data['devices'][0]['after'][0][3:5],['0-B20','存储器'])

    def test_source_pin_name_only(self):
        data=m.model(built())
        self.assertEqual(data['devices'][0]['before'][0][6],'SPI0_SCK')
        self.assertEqual(data['devices'][0]['after'][0][6],'SPI0_SCK')
        self.assertEqual(data['devices'][1]['after'][0][6],'I2C0_SCL')
        with self.assertRaises(ValueError): m.pin_names(['U12[10:SCK] -> U20[1]'])

    def test_network_operations(self):
        s=built(); data=m.model(s)
        self.assertEqual(data['columns'][13],'网络操作')
        self.assertEqual(data['devices'][0]['before'][3][13],'修改')
        self.assertEqual(data['devices'][0]['after'][3][13],'修改')
        self.assertEqual(data['devices'][1]['after'][0][13],'新增')
        self.assertEqual(data['devices'][2]['before'][0][13],'删除')
        self.assertEqual(s['original']['O3']['action'],'KEEP')

    def test_deleted_network_visible_in_original(self):
        s=built()
        m.propose(s,{'changes':[{'id':'DEL-O0','device_id':'DEV-U12','original_id':'O0','action':'DELETE',
                                'reason':'explicit removal','evidence':['synthetic:delete']}]})
        data=m.model(s)
        self.assertEqual(data['devices'][0]['before'][0][13],'删除')
        self.assertFalse(any(r[16]=='O0' for r in data['devices'][0]['after']))

    def test_missing_pin_names_never_extract_from_chain(self):
        manifest,cap,maps,targets,changes=fixture()
        cap['rows'][0].pop('source_pin_names')
        s=m.new_state(manifest); m.capture(s,cap); m.freeze(s,True); m.map_rows(s,maps)
        self.assertEqual(m.model(s)['devices'][0]['before'][0][6],'')

    def test_destination_change_preserves_source_name(self):
        s=built()
        m.propose(s,{'changes':[{'id':'MOVE-O0','device_id':'DEV-U12','original_id':'O0','action':'CHANGE',
            'reason':'改变目的端，源端保持','evidence':['synthetic:move'],
            'fields':{'destination_block_id':'B21'}}]})
        row=next(r for r in m.model(s)['devices'][0]['after'] if r[17]=='MOVE-O0')
        self.assertEqual(row[6],'SPI0_SCK')
        self.assertEqual(row[13],'修改')

    def test_reject_invented_name(self):
        s=built(); maps=fixture()[2]
        maps['mappings'][0]['endpoint']['source_block_name']='随意写的名字'
        with self.assertRaises(ValueError): m.map_rows(s,maps)

    def test_page_ids_and_empty_name(self):
        blocks=diagram_identity.catalog([{'type':'graph','id':p,'children':[{'type':'block','id':337,'name':''}]} for p in [0,1]])
        self.assertEqual(diagram_identity.resolve(blocks,{'page_id':0,'block_id':337}),('0-337',''))
        with self.assertRaises(ValueError): diagram_identity.resolve(blocks,337)

    def test_unknown_block_rejected(self):
        with self.assertRaises(ValueError): diagram_identity.resolve(built()['manifest']['diagram_catalog'],'fake')

    def test_unresolved_not_done(self):
        self.assertTrue(any(p['action']=='RESOLVE_ROW_DETAILS' for p in m.next_actions(built())))

    def test_new_device_unknown_pin_note(self):
        rows=m.modified_rows(built())
        self.assertFalse(any('端点已变更' in str(r.get('issues',[])) for r in rows if r['device_id']=='NEW-SENSOR'))

    def test_verified_branch_does_not_stop_other_paths(self):
        s={'budget':{'used':0,'max':20},'devices':{'D':{'info_status':'LOADED','pins_status':'LOADED'}},
           'interfaces':{'I':{'status':'VERIFIED','paths':[{'verified':True},{'verified':None}]}}}
        self.assertEqual(legacy.determine_phase(s),'TRACE_AND_VERIFY')
        s['interfaces']['I']['paths'][1]['verified']=False
        self.assertEqual(legacy.determine_phase(s),'DONE')

    def test_string_false_connection(self):
        pin=legacy.normalize_pin({'pin_number':'1','net_name':'','connected':'false'})
        self.assertIs(pin['connected'],False)


def verify_xlsx(filename):
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(filename) as archive:
        assert archive.testzip() is None
        workbook=ET.fromstring(archive.read('xl/workbook.xml'))
        names=[s.attrib['name'] for s in workbook.findall('s:sheets/s:sheet',ns)]
        before=Path(filename).name.startswith('原始')
        expected=['BLOCK_INFO','U12','NEW-SENSOR'] + (['原始接口_删除'] if before else [])
        assert names==expected,names
        strings=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            root=ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings=[''.join(n.itertext()) for n in root.findall('s:si',ns)]
        def cells(xml):
            result={}
            for cell in ET.fromstring(xml).findall('.//s:c',ns):
                assert cell.find('s:f',ns) is None,'演示工作簿不应有公式'
                v=cell.find('s:v',ns)
                if cell.attrib.get('t')=='s': val=strings[int(v.text)]
                elif cell.attrib.get('t')=='inlineStr': val=''.join(cell.find('s:is',ns).itertext())
                else: val=v.text if v is not None else ''
                result[cell.attrib['r']]=val
            return result
        root=ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
        c=cells(archive.read('xl/worksheets/sheet2.xml'))
        assert [c[f'{chr(65+i)}6'] for i in range(10)]==m.COLS[:10]
        assert float(c['I7'])==0.9
        assert c['J10']==('SPI0_CS0' if before else 'SPI0_FLASH_CS_N')
        assert c['K11']=='SPI1'
        assert c['A7']=='0-B12' and c['B7']=='主控'
        assert c['G7']=='SPI0_SCK' and c['N6']=='网络操作' and c['N10']=='修改'
        assert c.get('A15','')==''
        if before:
            removed=cells(archive.read('xl/worksheets/sheet4.xml'))
            assert removed['G7']=='TX' and removed['N7']=='删除'
        assert root.find('.//s:pane',ns) is not None
        c=cells(archive.read('xl/worksheets/sheet1.xml'))
        assert c['H7']=='5' and c['I7']=='5' and c['H8']=='0' and c['I8']=='2'
        print('XLSX结构验证通过：独立版本、10列顺序、框图id/name、网络名、SPI1实例、记录计数')


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--demo-dir'); parser.add_argument('--xlsx')
    args=parser.parse_args()
    if args.xlsx:
        verify_xlsx(args.xlsx)
    elif args.demo_dir:
        dest=Path(args.demo_dir)
        for name,value in zip(['manifest','original','mappings','targets','changes'],fixture()):
            m.save(dest/(name+'.json'),value)
        m.save(dest/'diagram.json',fixture()[0]['diagram'])
        state=built(); m.save(dest/'state.json',state); m.save(dest/'model.json',m.model(state))
        print('合成演示数据已生成: '+str(dest))
    else:
        unittest.main(argv=['tests'],verbosity=2)
