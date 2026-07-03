import re
import json
import os

def parse_iso27001(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    items = []
    mode = "body"  # "body" or "annex"
    
    current_section = ""
    current_subsection_id = ""
    current_subsection_title = ""
    current_content = []
    
    def flush_current():
        nonlocal current_subsection_id, current_subsection_title, current_content
        if current_subsection_id and (current_content or current_subsection_title):
            content_str = "\n".join(current_content).strip()
            # 判斷 type
            item_type = "control" if mode == "annex" else "clause"
            # 決定 ID 前綴
            id_prefix = "control_" if mode == "annex" else "clause_"
            
            items.append({
                "id": f"{id_prefix}{current_subsection_id}",
                "type": item_type,
                "section": current_section,
                "subsection": f"{current_subsection_id} {current_subsection_title}",
                "title": current_subsection_title,
                "content": content_str
            })
            current_content = []

    for line in lines:
        line_str = line.strip()
        if not line_str:
            # 空白行，若有內容則保留作為換行，否則跳過
            if current_content and current_content[-1] != "":
                current_content.append("")
            continue
            
        # 偵測模式切換
        if line_str == "附錄 A":
            flush_current()
            mode = "annex"
            current_section = "附錄 A"
            current_subsection_id = ""
            current_subsection_title = ""
            continue
            
        if mode == "body":
            # 匹配本文大章節 (例如 "4. 組織全景")
            section_match = re.match(r'^(\d+)\.\s*(.*)', line_str)
            # 匹配本文子章節 (例如 "4.1 瞭解組織及其全景" 或 "6.1.1 一般要求")
            sub_match = re.match(r'^(\d+\.\d+(?:\.\d+)?)\s+(.*)', line_str)
            
            if sub_match:
                # 遇到新的子章節，先存入上一個
                flush_current()
                current_subsection_id = sub_match.group(1)
                current_subsection_title = sub_match.group(2)
            elif section_match:
                flush_current()
                # 遇到大章節
                current_section = line_str
                # 預設大章節也可以是一個 subsection，以防底下直接有內容
                current_subsection_id = section_match.group(1)
                current_subsection_title = section_match.group(2)
            else:
                # 一般內容行
                current_content.append(line_str)
                
        elif mode == "annex":
            # 匹配附錄大分類 (例如 "5 組織控制措施" 或 "6. 人員控制")
            annex_section_match = re.match(r'^([5-8])\.?\s+(.*控制.*)', line_str)
            # 匹配附錄控制項 (例如 "5.1 資訊安全政策")
            annex_sub_match = re.match(r'^([5-8]\.\d+)\s+(.*)', line_str)
            
            if annex_sub_match:
                flush_current()
                current_subsection_id = annex_sub_match.group(1)
                current_subsection_title = annex_sub_match.group(2)
            elif annex_section_match:
                flush_current()
                current_section = line_str
                # 預設大分類也可以作為一個 subsection
                current_subsection_id = annex_section_match.group(1)
                current_subsection_title = annex_section_match.group(2)
            else:
                current_content.append(line_str)
                
    # 存入最後一個
    flush_current()
    
    # 清理 content 中的多餘空行，並確保 content 格式漂亮
    for item in items:
        # 去除 content 字串首尾的空行，以及連續空行
        lines_clean = [l.strip() for l in item["content"].split("\n")]
        # 過濾多餘的空行
        final_lines = []
        for l in lines_clean:
            if l == "" and final_lines and final_lines[-1] == "":
                continue
            final_lines.append(l)
        # 如果最後一行是空行，去掉它
        if final_lines and final_lines[-1] == "":
            final_lines.pop()
        item["content"] = "\n".join(final_lines)
        
    return items

if __name__ == "__main__":
    base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    input_file = os.path.join(base_dir, "cht.md")
    output_file = os.path.join(base_dir, "iso27001_structure.json")
    
    print(f"Parsing {input_file}...")
    parsed_items = parse_iso27001(input_file)
    
    # 輸出統計
    clauses = [i for i in parsed_items if i["type"] == "clause"]
    controls = [i for i in parsed_items if i["type"] == "control"]
    print(f"Found {len(parsed_items)} items in total:")
    print(f"  - Clauses (本文條文): {len(clauses)}")
    print(f"  - Controls (控制措施): {len(controls)}")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(parsed_items, f, ensure_ascii=False, indent=2)
        
    print(f"Structured data saved to {output_file}")
