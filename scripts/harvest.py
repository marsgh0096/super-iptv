import os
import asyncio
import httpx
import base64
from typing import List, Dict, Optional

# ================= 配置区域 =================
# 针对北京地区，通过奇安信鹰图进行宽泛搜索，靠主动流测活自动过滤并动态标注运营商
HUNTER_QUERY = 'app.name="udpxy" && ip.city="北京市"'
TEST_MULTICAST = "239.3.1.150:8000"  # 北京卫视组播

# 待测试的联通核心频道列表（组播 IP 映射）
CHANNELS = {
    "bjws": {"name": "北京卫视", "multicast": "239.3.1.150:8000"},
    "btvwy": {"name": "BRTV 文艺", "multicast": "239.3.1.209:8000"},
    "btvxw": {"name": "BRTV 新闻", "multicast": "239.3.1.151:8000"},
    "kaku": {"name": "卡酷少儿", "multicast": "239.3.1.152:8000"},
}
# ============================================

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
    
    candidates = []
    
    for url in api_endpoints:
        print(f"📡 尝试请求接口: {url}")
        # 奇安信国际站 (hunter.how) 接收的参数名为 "query"，国内站为 "search"
        query_param_name = "query" if "hunter.how" in url else "search"
        
        params = {
            "api-key": key,
            query_param_name: search_val,
            "page": 1,
            "page_size": 50,
            "is_web": 3
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    # 兼容国内站(code=200)和国际站(code=200)的响应格式
                    code = data.get("code")
                    if code == 200:
                        # 兼容国际站的 data.list 和国内站的 data.arr
                        data_obj = data.get("data", {}) or {}
                        arr = data_obj.get("list", []) or data_obj.get("arr", []) or []
                        
                        for item in arr:
                            ip = item.get("ip")
                            port = item.get("port")
                            # 提取运营商字段，优先 as_org 或 isp
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
    # 动态检测奇安信鹰图的密钥环境变量
    hunter_key = os.environ.get("HUNTER_KEY") or os.environ.get("HUNTER_API_KEY")
    if not hunter_key:
        print("❌ 未检测到 HUNTER_KEY 或 HUNTER_API_KEY 环境变量！请在 GitHub Secrets 中配置。")
        return
        
    # 1. 抓取节点
    candidates = await fetch_hunter_nodes(hunter_key)
    if not candidates:
        print("❌ 未从奇安信鹰图获取到任何可用北京 udpxy 候选节点。")
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
