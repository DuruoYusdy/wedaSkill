"""从框图JSON生成图页id-block id及原始name；不接受自由生成的名称。"""
import copy


def catalog(diagram):
    blocks = {}

    def walk(node, page=None):
        if isinstance(node, list):
            for child in node:
                walk(child, page)
            return
        if not isinstance(node, dict):
            raise ValueError("框图节点必须为对象")
        if node.get("type") == "graph":
            if node.get("id") is None:
                raise ValueError("图页graph缺少id，不能用数组序号代替")
            page = str(node["id"])
        elif node.get("type") == "block" and "id" in node and page is not None:
            bid = str(node["id"])
            key = page + "-" + bid
            if node["id"] is None or not isinstance(node.get("name"), str):
                raise ValueError("block必须提供id和字符串name（允许空名称）")
            if key in blocks:
                raise ValueError("重复或拼接冲突的block标识: " + key)
            blocks[key] = {"page_id": page, "block_id": bid, "name": node["name"]}
        if "graph" in node:
            walk(node["graph"], page)
        for child in node.get("children", []):
            walk(child, page)

    walk(diagram)
    if not blocks:
        raise ValueError("框图没有可索引的graph/block；API包装层请按真实结构解包，不推测图页ID")
    return blocks


def resolve(blocks, ref):
    if isinstance(ref, dict):
        key = str(ref["page_id"]) + "-" + str(ref["block_id"])
        match = blocks.get(key)
        if match and (match['page_id'], match['block_id']) != (str(ref['page_id']), str(ref['block_id'])):
            raise ValueError("block复合标识拼接冲突")
    else:
        key = str(ref)
        match = blocks.get(key)
        if not match:
            candidates = [(k, v) for k, v in blocks.items() if v["block_id"] == key]
            if len(candidates) != 1:
                raise ValueError("block不存在或跨图页歧义，请给出page_id和block_id: " + key)
            key, match = candidates[0]
    if not match:
        raise ValueError("block不在当前框图JSON中: " + key)
    return key, match["name"]


def fields(blocks, raw, prefixes=("source_", "destination_")):
    result = copy.deepcopy(raw)
    for prefix in prefixes:
        id_key, name_key = prefix + "block_id", prefix + "block_name"
        ref = result.get(id_key)
        if ref is None or ref == "":
            if result.get(name_key):
                raise ValueError("没有框图block引用，不能只填写名称")
            continue
        key, name = resolve(blocks, ref)
        if name_key in result and result[name_key] != name:
            raise ValueError("block名称与框图name不一致: " + key)
        result[id_key], result[name_key] = key, name
    return result
