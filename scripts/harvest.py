import os
import asyncio
import httpx
import base64
from typing import List, Dict, Optional

# ================= 配置区域 =================
# 只针对北京地区，去除 ISP 限制以最大化获取候选，靠主动流测活自动筛选与标注运营商
ZOOMEYE_QUERIES = [
    'app:"udpxy" && city:"Beijing"',
    'app:"udpxy" && subdivisions:"Beijing"',
    'udpxy && city:"Beijing"',
]

TEST_MULTICAST = "239.3.1.150:8000"  # 北京卫视组播

# 待测试的联通核心频道列表（组播 IP 映射）
CHANNELS = {
    "bjws": {"name": "北京卫视", "multicast": "239.3.1.150:8000"},
    "btvwy": {"name": "BRTV 文艺", "multicast": "239.3.1.209:8000"},
    "btvxw": {"name": "BRTV 新闻", "multicast": "239.3.1.151:8000"},
    "kaku": {"name": "卡酷少儿", "multicast": "239.3.1.152:8000"},
}
# ============================================

async def fetch_fofa_nodes(key: str) -> List[Dict]:
    """通过 FOFA 开放接口抓取北京的 udpxy 节点"""
    print("🔍 正在通过 FOFA 接口检索北京 udpxy 节点...")
    query = 'app="udpxy" && city="Beijing"'
    qbase64 = base64.b64encode(query.encode('utf-8')).decode('utf-8')
    url = "https://fofa.info/api/v1/search/all"
    params = {
        "key": key,
        "qbase64": qbase64,
        "fields": "ip,port,org",
        "size": 50
    }
    candidates = []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("error") == False:
                    results = data.get("results", []) or []
                    for item in results:
                        if len(item) >= 2:
                            ip = item[0]
                            port = item[1]
                            isp = item[2] if len(item) > 2 else "未知运营商"
                            candidates.append({
                                "url": f"http://{ip}:{port}",
                                "isp": isp
                            })
                    if candidates:
                        print(f"✅ FOFA 检索成功！获取到 {len(candidates)} 个候选节点。")
                        return candidates
                else:
                    print(f"⚠️ FOFA API 返回错误: {data.get('errmsg')}")
            else:
                print(f"⚠️ FOFA API 状态码异常 {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"获取 FOFA 数据出错: {e}")
    return []

async def fetch_hunter_nodes(key: str) -> List[Dict]:
    """通过 奇安信鹰图 (Hunter) 开放接口抓取北京的 udpxy 节点"""
    print("🔍 正在通过 奇安信鹰图 (Hunter) 接口检索北京 udpxy 节点...")
    query = 'app.name="udpxy" && ip.city="北京市"'
    search_val = base64.urlsafe_b64encode(query.encode('utf-8')).decode('utf-8')
    url = "https://hunter.qianxin.com/openApi/search"
    params = {
        "api-key": key,
        "search": search_val,
        "page": 1,
        "page_size": 50,
        "is_web": 3
    }
    candidates = []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200:
                    arr = data.get("data", {}).get("arr", []) or []
                    for item in arr:
                        ip = item.get("ip")
                        port = item.get("port")
                        isp = item.get("as_org", "未知运营商")
                        if ip and port:
                            candidates.append({
                                "url": f"http://{ip}:{port}",
                                "isp": isp
                            })
                    if candidates:
                        print(f"✅ Hunter 检索成功！获取到 {len(candidates)} 个候选节点。")
                        return candidates
                else:
                    print(f"⚠️ Hunter API 返回错误: {data.get('message')}")
            else:
                print(f"⚠️ Hunter API 状态码异常 {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"获取 Hunter 数据出错: {e}")
    return []

async def fetch_zoomeye_nodes(api_key: str) -> List[Dict]:
    """通过 ZoomEye 国际站接口抓取北京的 udpxy 节点"""
    print("🔍 正在通过 ZoomEye 接口检索北京 udpxy 节点...")
    headers = {"API-KEY": api_key, "User-Agent": "ZoomEye-Python-SDK"}
    
    for query in ZOOMEYE_QUERIES:
        print(f"🔍 正在尝试 ZoomEye 查询: {query}")
        candidates = []
        try:
            async with httpx.AsyncClient() as client:
                url = "https://api.zoomeye.ai/host/search"
                resp = await client.get(
                    url, 
                    headers=headers, 
                    params={"query": query, "page": 1}, 
                    timeout=10.0
                )
                if resp.status_code == 200:
                    matches = resp.json().get("matches", []) or []
                    for match in matches:
                        ip = match.get("ip")
                        port = match.get("portinfo", {}).get("port")
                        isp = match.get("geoinfo", {}).get("isp", "未知运营商")
                        if ip and port:
                            candidates.append({
                                "url": f"http://{ip}:{port}",
                                "isp": isp
                            })
                    if candidates:
                        print(f"✅ ZoomEye 查询成功！获取到 {len(candidates)} 个北京候选节点。")
                        return candidates
                    else:
                        print("⚠️ 该查询未返回任何节点，尝试下一个候选查询...")
                else:
                    print(f"⚠️ ZoomEye API 返回状态码 {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"获取 ZoomEye 数据出错: {e}")
            
    print("❌ 所有候选 ZoomEye 查询均未获取到任何北京节点。")
    return []

async def verify_node(candidate: Dict) -> Optional[Dict]:
    node_url = candidate["url"]
    isp = candidate["isp"]
    status_url = f"{node_url}/status/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(status_url, headers=headers, timeout=2.0)
            if r.status_code == 200 and "udpxy status" in r.text.lower():
                active = r.text.count("<td>[")  # 统计已有的活跃连接数
                
                # 拿北京卫视组播测试该节点连通性
                stream_url = f"{node_url}/udp/{TEST_MULTICAST}"
                async with client.stream("GET", stream_url, headers=headers, timeout=2.5) as stream_resp:
                    if stream_resp.status_code == 200:
                        return {
                            "node": node_url, 
                            "connections": active, 
                            "isp": isp
                        }
    except Exception:
        pass
    return None

async def main():
    # 动态检测所有支持的测绘引擎密钥
    fofa_key = os.environ.get("FOFA_KEY")
    hunter_key = os.environ.get("HUNTER_KEY") or os.environ.get("HUNTER_API_KEY")
    zoomeye_key = os.environ.get("ZOOMEYE_KEY")
    
    candidates = []
    
    # 按照优先级：FOFA -> Hunter -> ZoomEye 进行故障转移与避险尝试
    if fofa_key:
        candidates = await fetch_fofa_nodes(fofa_key)
        
    if not candidates and hunter_key:
        candidates = await fetch_hunter_nodes(hunter_key)
        
    if not candidates and zoomeye_key:
        candidates = await fetch_zoomeye_nodes(zoomeye_key)
        
    if not candidates:
        print("❌ 未检测到任何可用的测绘平台密钥，或者所有已配置的平台均检索失败（可能是额度用尽）。")
        return
        
    # 2. 并发测活
    print(f"🔄 正在对 {len(candidates)} 个北京候选节点进行多线程高并发流连通性与负载测试...")
    tasks = [verify_node(cand) for cand in candidates]
    results = await asyncio.gather(*tasks)
    healthy = [r for r in results if r is not None]
    
    if not healthy:
        print("❌ 没有找到任何可通过北京卫视组播流验证的健康公网节点。")
        return
        
    # 按连接负载升序排序
    healthy.sort(key=lambda x: x["connections"])
    best_node = healthy[0]["node"]
    best_isp = healthy[0]["isp"]
    print(f"🌟 本轮最空闲的健康节点: {best_node}，运营商: {best_isp}，可用健康节点共 {len(healthy)} 个。")
    
    # 3. 编译并输出为标准的播放列表文件 playlist.m3u
    m3u_lines = ["#EXTM3U"]
    for ch_id, ch_meta in CHANNELS.items():
        # 拼接出直连最优节点的 M3U 单播流链接
        play_url = f"{best_node}/udp/{ch_meta['multicast']}"
        # 在分组名和频道名中动态标注出具体的运营商
        m3u_lines.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-logo="" group-title="北京专网台 ({best_isp})",{ch_meta["name"]} ({best_isp})')
        m3u_lines.append(play_url)
        
    # 写入文件，交由 GitHub commit 归档
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
    print("✅ playlist.m3u 编译并写入完成！")

if __name__ == "__main__":
    asyncio.run(main())
