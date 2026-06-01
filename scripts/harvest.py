import os
import asyncio
import httpx
from typing import List, Dict, Optional

# ================= 区域与频道多源配置区域 =================
# 您可以根据需要随时启用/禁用或添加更多省市和运营商的组播源扫描配置
REGIONS = {
    "bj_unicom": {
        "name": "北京联通",
        "test_multicast": "239.3.1.150:8000",  # 用于测活的北京卫视组播地址
        "queries": [
            'app:"udpxy" && city:"Beijing" && isp:"China Unicom"',
            'app:"udpxy" && subdivisions:"Beijing" && isp:"China Unicom"',
            'app:"udpxy" && country:"CN" && isp:"China Unicom"',  # 宽泛搜索，靠测活自动过滤出实际可播放的节点
        ],
        "channels": {
            "bjws": {"name": "北京卫视", "multicast": "239.3.1.150:8000"},
            "btvwy": {"name": "BRTV 文艺", "multicast": "239.3.1.209:8000"},
            "btvxw": {"name": "BRTV 新闻", "multicast": "239.3.1.151:8000"},
            "kaku": {"name": "卡酷少儿", "multicast": "239.3.1.152:8000"},
        }
    },
    "sc_telecom": {
        "name": "四川电信",
        "test_multicast": "239.93.1.18:5140",  # 用于测活的四川卫视组播地址
        "queries": [
            'app:"udpxy" && subdivisions:"Sichuan" && isp:"China Telecom"',
            'app:"udpxy" && country:"CN" && isp:"China Telecom"',  # 宽泛搜索，靠测活自动筛选
        ],
        "channels": {
            "scws": {"name": "四川卫视", "multicast": "239.93.1.18:5140"},
            "scys": {"name": "四川影视", "multicast": "239.93.1.21:5140"},
            "scxw": {"name": "四川新闻", "multicast": "239.93.1.23:5140"},
        }
    },
    "gd_telecom": {
        "name": "广东电信",
        "test_multicast": "239.77.1.1:5146",  # 用于测活的广东卫视组播地址
        "queries": [
            'app:"udpxy" && subdivisions:"Guangdong" && isp:"China Telecom"',
            'app:"udpxy" && country:"CN" && isp:"China Telecom"',  # 宽泛搜索，靠测活自动筛选
        ],
        "channels": {
            "gdws": {"name": "广东卫视", "multicast": "239.77.1.1:5146"},
            "gdzj": {"name": "广东珠江", "multicast": "239.77.1.2:5146"},
            "gdgg": {"name": "广东公共", "multicast": "239.77.1.3:5146"},
            "gdnews": {"name": "广东新闻", "multicast": "239.77.1.4:5146"},
        }
    }
}

# 启用的区域列表，您可以自由添加或注释掉不想扫描的区域
ACTIVE_REGIONS = ["bj_unicom", "sc_telecom", "gd_telecom"]
# ==========================================================

async def fetch_zoomeye_nodes(api_key: str, queries: List[str]) -> List[str]:
    headers = {"API-KEY": api_key, "User-Agent": "ZoomEye-Python-SDK"}
    
    for query in queries:
        print(f"🔍 正在尝试 ZoomEye 查询: {query}")
        nodes = []
        try:
            async with httpx.AsyncClient() as client:
                url = "https://api.zoomeye.org/host/search"
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
                        if ip and port:
                            nodes.append(f"http://{ip}:{port}")
                    if nodes:
                        print(f"✅ 查询成功！获取到 {len(nodes)} 个候选节点。")
                        return nodes
                    else:
                        print("⚠️ 该查询未返回任何节点，尝试下一个候选查询...")
                else:
                    print(f"⚠️ ZoomEye API 返回状态码 {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"获取 ZoomEye 数据出错: {e}")
            
    return []

async def verify_node(node_url: str, test_multicast: str) -> Optional[Dict]:
    status_url = f"{node_url}/status/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(status_url, headers=headers, timeout=2.0)
            if r.status_code == 200 and "udpxy status" in r.text.lower():
                active = r.text.count("<td>[")  # 统计已有连接数
                
                # 用该区域的组播源地址测试连通性
                stream_url = f"{node_url}/udp/{test_multicast}"
                async with client.stream("GET", stream_url, headers=headers, timeout=2.5) as stream_resp:
                    if stream_resp.status_code == 200:
                        return {"node": node_url, "connections": active}
    except Exception:
        pass
    return None

async def main():
    api_key = os.environ.get("ZOOMEYE_KEY")
    if not api_key:
        print("❌ 未检测到 ZOOMEYE_KEY 环境变量！")
        return
        
    m3u_lines = ["#EXTM3U"]
    any_success = False
    
    for r_id in ACTIVE_REGIONS:
        if r_id not in REGIONS:
            continue
            
        r_meta = REGIONS[r_id]
        print(f"\n🚀 === 开始扫描区域: {r_meta['name']} ===")
        
        # 1. 抓取节点
        raw_nodes = await fetch_zoomeye_nodes(api_key, r_meta["queries"])
        if not raw_nodes:
            print(f"⚠️ 区域 {r_meta['name']} 未发现任何候选节点，跳过。")
            continue
            
        # 2. 并发测活
        tasks = [verify_node(node, r_meta["test_multicast"]) for node in raw_nodes]
        results = await asyncio.gather(*tasks)
        healthy = [r for r in results if r is not None]
        
        if not healthy:
            print(f"⚠️ 区域 {r_meta['name']} 没有找到任何健康的公网 udpxy 代理节点。")
            continue
            
        # 按连接负载升序排序，选择最空闲的可用节点
        healthy.sort(key=lambda x: x["connections"])
        best_node = healthy[0]["node"]
        print(f"🌟 区域 {r_meta['name']} 最空闲的健康节点: {best_node}，可用健康节点共 {len(healthy)} 个。")
        
        # 3. 编译该区域频道的播放流链接
        for ch_id, ch_meta in r_meta["channels"].items():
            play_url = f"{best_node}/udp/{ch_meta['multicast']}"
            m3u_lines.append(f'#EXTINF:-1 tvg-id="{ch_id}" tvg-logo="" group-title="{r_meta["name"]}专网台",{ch_meta["name"]}')
            m3u_lines.append(play_url)
            
        any_success = True
        
    if not any_success:
        print("\n❌ 遗憾：所有区域均未能扫描到任何健康节点，不更新 playlist.m3u 文件！")
        return
        
    # 写入文件，交由 GitHub commit 归档
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
        
    print("\n🎉 全局 playlist.m3u 编译并写入完成！")

if __name__ == "__main__":
    asyncio.run(main())
