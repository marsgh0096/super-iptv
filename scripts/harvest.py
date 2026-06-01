import os
import asyncio
import httpx
import base64
import datetime
from typing import List, Dict, Optional

# ================= 配置区域 =================
# 只针对北京地区，通过测绘引擎进行宽泛搜索，靠主动流测活自动过滤并动态标注运营商
HUNTER_QUERY = 'app.name="udpxy" && ip.city="北京市"'
QUAKE_QUERY = 'app:"udpxy" AND city:"Beijing"'
TEST_MULTICAST = "239.3.1.150:8000"  # 北京卫视组播

# 待测试的联通核心频道列表（组播 IP 映射）
CHANNELS = {
    "bjws": {"name": "北京卫视", "multicast": "239.3.1.150:8000"},
    "btvwy": {"name": "BRTV 文艺", "multicast": "239.3.1.209:8000"},
    "btvxw": {"name": "BRTV 新闻", "multicast": "239.3.1.151:8000"},
    "kaku": {"name": "卡酷少儿", "multicast": "239.3.1.152:8000"},
}
# ============================================

async def fetch_quake_nodes(key: str) -> List[Dict]:
    """通过 360 Quake 开放接口抓取北京的 udpxy 节点（极其稳定，赠送免费 API 额度，支持海外 Actions 直接访问）"""
    print("🔍 正在通过 360 Quake 接口检索北京 udpxy 节点...")
    url = "https://quake.360.net/api/v3/search/quake_service"
    headers = {
        "X-QuakeToken": key,
        "Content-Type": "application/json"
    }
    body = {
        "query": QUAKE_QUERY,
        "start": 0,
        "size": 50
    }
    candidates = []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=body, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if str(data.get("code")) == "0":
                    results = data.get("data", []) or []
                    for item in results:
                        ip = item.get("ip")
                        port = item.get("port")
                        location = item.get("location", {}) or {}
                        isp = location.get("isp") or item.get("org") or "未知运营商"
                        if ip and port:
                            candidates.append({
                                "url": f"http://{ip}:{port}",
                                "isp": isp
                            })
                    if candidates:
                        print(f"✅ 360 Quake 检索成功！获取到 {len(candidates)} 个北京候选节点。")
                        return candidates
                else:
                    print(f"⚠️ 360 Quake API 返回错误: {data.get('message')}")
            else:
                print(f"⚠️ 360 Quake API 状态码异常 {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"获取 360 Quake 数据出错: {e}")
    return []

async def fetch_hunter_nodes(key: str) -> List[Dict]:
    """通过 奇安信鹰图 (Hunter.how / Hunter.qianxin.com) 开放接口抓取北京的 udpxy 节点"""
    print("🔍 正在通过 奇安信鹰图 (Hunter) 接口检索北京 udpxy 节点...")
    
    # URL 安全的 base64 编码
    search_val = base64.urlsafe_b64encode(HUNTER_QUERY.encode('utf-8')).decode('utf-8')
    
    # 国际站与国内站做高容错请求支持
    api_endpoints = [
        "https://api.hunter.how/search",            # 奇安信国际站 (hunter.how)
        "https://hunter.qianxin.com/openApi/search"  # 奇安信国内站 (hunter.qianxin.com)
    ]
    
    # 部分平台接口（如国际站）强制要求带上时间范围
    today = datetime.date.today()
    one_year_ago = today - datetime.timedelta(days=365)
    start_time = one_year_ago.strftime("%Y-%m-%d")
    end_time = today.strftime("%Y-%m-%d")
    
    candidates = []
    
    for url in api_endpoints:
        print(f"📡 尝试请求接口: {url}")
        query_param_name = "query" if "hunter.how" in url else "search"
        
        params = {
            "api-key": key,
            query_param_name: search_val,
            "page": 1,
            "page_size": 50,
            "is_web": 3,
            "start_time": start_time,
            "end_time": end_time
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    code = data.get("code")
                    if code == 200:
                        data_obj = data.get("data", {}) or {}
                        arr = data_obj.get("list", []) or data_obj.get("arr", []) or []
                        
                        for item in arr:
                            ip = item.get("ip")
                            port = item.get("port")
                            isp = item.get("as_org", "") or item.get("isp", "") or "未知运营商"
                            if ip and port:
                                candidates.append({
                                    "url": f"http://{ip}:{port}",
                                    "isp": isp
                                })
                        if candidates:
                            print(f"✅ 鹰图接口检索成功！获取到 {len(candidates)} 个北京候选节点。")
                            return candidates
                    else:
                        print(f"⚠️ 鹰图 API 返回非成功状态码 {code}: {data.get('message')}")
                else:
                    print(f"⚠️ 鹰图 API 请求失败，HTTP 状态码: {resp.status_code}")
        except Exception as e:
            print(f"请求鹰图接口 {url} 出错: {e}")
            
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
                
                # 自适应检测 /rtp/ (国内 IPTV 组播主力协议) 和 /udp/ (少数裸组播)
                for proto in ["rtp", "udp"]:
                    stream_url = f"{node_url}/{proto}/{TEST_MULTICAST}"
                    try:
                        async with client.stream("GET", stream_url, headers=headers, timeout=2.5) as stream_resp:
                            if stream_resp.status_code == 200:
                                return {
                                    "node": node_url, 
                                    "connections": active, 
                                    "isp": isp,
                                    "proto": proto
                                }
                    except Exception:
                        continue
    except Exception:
        pass
    return None

async def main():
    # 动态检测所有支持的测绘引擎密钥
    quake_key = os.environ.get("QUAKE_KEY") or os.environ.get("QUAKE_TOKEN")
    hunter_key = os.environ.get("HUNTER_KEY") or os.environ.get("HUNTER_API_KEY")
    
    candidates = []
    
    # 优先使用免费额度极高、且完全支持免费 API 调用的 360 Quake 引擎进行快速避险
    if quake_key:
        candidates = await fetch_quake_nodes(quake_key)
        
    # 如果 Quake 未配置或检索为空，则故障降级到奇安信鹰图接口
    if not candidates and hunter_key:
        candidates = await fetch_hunter_nodes(hunter_key)
        
    if not candidates:
        print("❌ 未检测到任何可用的测绘平台密钥（请在 Secrets 配置 QUAKE_KEY），或者平台检索失败。")
        return
        
    # 2. 并发测活
    print(f"🔄 正在对 {len(candidates)} 个北京候选节点进行并发连通性与负载测试...")
    tasks = [verify_node(cand) for cand in candidates]
    results = await asyncio.gather(*tasks)
    healthy = [r for r in results if r is not None]
    
    if not healthy:
        print("❌ 没有找到任何可通过北京卫视组播流验证的健康公网节点。")
        return
        
    # 按连接负载（连接数）升序排序，选择最空闲的节点
    healthy.sort(key=lambda x: x["connections"])
    best_node = healthy[0]["node"]
    best_isp = healthy[0]["isp"]
    best_proto = healthy[0].get("proto", "rtp")
    print(f"🌟 本轮最空闲的健康节点: {best_node}，运营商: {best_isp}，协议前缀: {best_proto}，可用健康节点共 {len(healthy)} 个。")
    
    # 3. 编译并输出为标准的播放列表文件 playlist.m3u
    m3u_lines = ["#EXTM3U"]
    for ch_id, ch_meta in CHANNELS.items():
        # 拼接出直连最优节点的 M3U 单播流链接 (自动使用测活成功的协议前缀 rtp 或 udp)
        play_url = f"{best_node}/{best_proto}/{ch_meta['multicast']}"
        # 在分组名和频道名中动态标注出具体的运营商
        m3u_lines.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-logo="" group-title="北京专网台 ({best_isp})",{ch_meta["name"]} ({best_isp})')
        m3u_lines.append(play_url)
        
    # 写入文件，交由 GitHub commit 归档
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
    print("✅ playlist.m3u 编译并写入完成！")

if __name__ == "__main__":
    asyncio.run(main())
