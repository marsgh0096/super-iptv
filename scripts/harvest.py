import os
import asyncio
import httpx
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

async def fetch_zoomeye_nodes(api_key: str) -> List[Dict]:
    headers = {"API-KEY": api_key, "User-Agent": "ZoomEye-Python-SDK"}
    
    for query in ZOOMEYE_QUERIES:
        print(f"🔍 正在尝试 ZoomEye 查询: {query}")
        candidates = []
        try:
            async with httpx.AsyncClient() as client:
                # 国际化节点使用 api.zoomeye.ai，确保在 GitHub Actions (海外环境) 下免受地域 403 拦截
                url = "https://api.zoomeye.ai/host/search"
                resp = await client.get(
                    url, 
                    headers=headers, 
                    params={"query": query, "page": 1}, 
                    timeout=10.0
                )
                if resp.status_code == 200:
                    matches = resp.json().get("matches", [])
                    for match in matches:
                        ip = match.get("ip")
                        port = match.get("portinfo", {}).get("port")
                        # 提取运营商信息
                        isp = match.get("geoinfo", {}).get("isp", "未知运营商")
                        if ip and port:
                            candidates.append({
                                "url": f"http://{ip}:{port}",
                                "isp": isp
                            })
                    if candidates:
                        print(f"✅ 查询成功！获取到 {len(candidates)} 个北京候选节点。")
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
    api_key = os.environ.get("ZOOMEYE_KEY")
    if not api_key:
        print("❌ 未检测到 ZOOMEYE_KEY 环境变量！")
        return
        
    # 1. 抓取节点
    candidates = await fetch_zoomeye_nodes(api_key)
    if not candidates:
        print("未发现任何候选节点。")
        return
        
    # 2. 并发测活
    tasks = [verify_node(cand) for cand in candidates]
    results = await asyncio.gather(*tasks)
    healthy = [r for r in results if r is not None]
    
    if not healthy:
        print("没有找到任何可通过北京卫视组播流验证的健康公网节点。")
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
