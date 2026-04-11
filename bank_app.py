import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import requests
from datetime import datetime
import re

st.set_page_config(page_title="银行流水分析工具", layout="wide", page_icon="💰")

st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: 600; color: #1E3A8A; text-align: center; margin-bottom: 1rem; }
    .sub-header { font-size: 1.2rem; color: #4B5563; text-align: center; margin-bottom: 2rem; }
    .rank-card { background-color: #F3F4F6; border-radius: 12px; padding: 1rem; margin: 0.5rem 0; transition: 0.2s; }
    .rank-card:hover { background-color: #E5E7EB; cursor: pointer; }
    .company-name { font-weight: 600; color: #2563EB; }
    .amount { font-family: monospace; font-size: 1rem; }
</style>
""", unsafe_allow_html=True)

# ---------- 汇率函数 ----------
@st.cache_data(ttl=3600)
def get_exchange_rates(date_str):
    try:
        url = f"https://api.exchangerate.host/latest?base=CNY&date={date_str}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            rates = data.get('rates', {})
            rates['CNY'] = 1.0
            if 'EUR' not in rates or rates.get('EUR', 0) == 0:
                rates['EUR'] = 7.8
            if 'USD' not in rates or rates.get('USD', 0) == 0:
                rates['USD'] = 7.2
            if 'HKD' not in rates or rates.get('HKD', 0) == 0:
                rates['HKD'] = 0.92
            if 'GBP' not in rates or rates.get('GBP', 0) == 0:
                rates['GBP'] = 9.1
            if 'JPY' not in rates or rates.get('JPY', 0) == 0:
                rates['JPY'] = 0.048
            return rates
        else:
            return default_rates()
    except Exception as e:
        st.warning(f"汇率获取失败，使用备用汇率: {e}")
        return default_rates()

def default_rates():
    return {'CNY': 1.0, 'USD': 7.2, 'EUR': 7.8, 'HKD': 0.92, 'GBP': 9.1, 'JPY': 0.048}

def safe_float_convert(val):
    if pd.isna(val):
        return 0.0
    s = str(val).strip()
    if s == '' or s.lower() in ('nan', 'none', 'null'):
        return 0.0
    s = s.replace(',', '')
    try:
        return float(s)
    except:
        return 0.0

def parse_date_cell(val):
    if pd.isna(val):
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date()
    if isinstance(val, (int, float)):
        if 19000101 <= int(val) <= 21001231:
            return datetime.strptime(str(int(val)), '%Y%m%d').date()
        else:
            try:
                return (datetime(1899, 12, 30) + pd.Timedelta(days=int(val))).date()
            except:
                return None
    if isinstance(val, str):
        try:
            return pd.to_datetime(val).date()
        except:
            pass
        date_part = val.split()[0] if ' ' in val else val
        for fmt in ('%Y%m%d', '%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(date_part, fmt).date()
            except:
                continue
        return None
    return None

def is_summary_row(row_cells):
    summary_keywords = ['总金额', '总笔数', '汇总', '合计', '小计', '总计', '明细', '记录条数',
                        '账户名称', '币种', '打印时间', '打印期限', '起始日期', '截至日期',
                        '收入总金额', '支出总金额', '收入总笔数', '支出总笔数']
    row_text = ' '.join(row_cells).lower()
    for kw in summary_keywords:
        if kw in row_text:
            return True
    return False

def find_header_row(df, max_rows=100):
    keywords = ['交易时间', '交易日', '日期', '记账日期', '交易日期', '起息日',
                '对方户名', '对方单位名称', '对方账号', '收款人名称', '付款人名称',
                '贷方发生额', '借方发生额', '贷方金额', '借方金额', '收入', '支出',
                '收入金额', '支出金额',
                '币种', '交易货币', '摘要', '附言', '用途', '借贷标志', '收支标志',
                '交易类型', '业务类型', '流水号', '序号', '账户账号', '转出', '转入',
                '交易金额', '对方账户名称', '交易流水号']
    for i in range(min(max_rows, len(df))):
        row_cells = [str(cell).lower() for cell in df.iloc[i]]
        if is_summary_row(row_cells):
            continue
        first_cell = row_cells[0] if row_cells else ''
        if first_cell.isdigit() and len(first_cell) <= 3:
            continue
        match_count = sum(1 for kw in keywords if any(kw in cell for cell in row_cells))
        if match_count >= 2:
            return i
    return None

def find_header_row_for_huaoxia(df, max_rows=100):
    for i in range(min(max_rows, len(df))):
        row_cells = [str(cell).strip() for cell in df.iloc[i]]
        if is_summary_row(row_cells):
            continue
        if len(row_cells) >= 2:
            if row_cells[0] == '序号' and '交易日期' in row_cells[1]:
                return i
        if any('序号' in cell for cell in row_cells) and any('交易日期' in cell for cell in row_cells):
            return i
    if len(df) > 7:
        first_cell = str(df.iloc[7, 0]).strip()
        if first_cell == '序号':
            return 7
    return None

def normalize_column_name(col):
    if not isinstance(col, str):
        return ''
    col = col.strip().replace(' ', '').replace('　', '')
    col = col.translate(str.maketrans('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    col = col.translate(str.maketrans('ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ', 'abcdefghijklmnopqrstuvwxyz'))
    return col.lower()

def identify_columns_enhanced(df, sheet_name):
    df.columns = [str(col) for col in df.columns]
    mapping = {
        'date': None, 'counterparty': None, 'currency': None,
        'remark': None, 'purpose': None,
        'amount_in': None, 'amount_out': None, 'amount': None, 'sign': None,
        'trans_type': None,
        'payer_name': None,
        'payee_name': None,
        'trans_date': None,
        'trans_time': None
    }

    # 特殊处理：意大利子公司（中行罗马分行）
    if '意大利子公司' in sheet_name or 'ZONSON SMART AUTO ITALIA' in sheet_name or '意大利' in sheet_name:
        for col in df.columns:
            col_str = str(col).strip()
            if col_str == '交易金额':
                mapping['amount'] = col
            elif col_str == '对方账户名称':
                mapping['counterparty'] = col
            elif col_str == '交易日期':
                mapping['date'] = col
            elif col_str == '交易币种':
                mapping['currency'] = col
        if mapping['date'] and mapping['amount'] and mapping['counterparty']:
            return mapping

    # 华夏银行精确匹配
    if '华夏' in sheet_name:
        for col in df.columns:
            col_str = str(col).strip()
            if col_str == '交易日期':
                mapping['date'] = col
            elif col_str == '交易时间':
                mapping['trans_time'] = col
            elif col_str == '收入金额':
                mapping['amount_in'] = col
            elif col_str == '支出金额':
                mapping['amount_out'] = col
            elif col_str == '对方户名':
                mapping['counterparty'] = col
        if mapping['date'] and (mapping['amount_in'] or mapping['amount_out']) and mapping['counterparty']:
            return mapping

    # 厦门国际银行
    if '厦门国际' in sheet_name or '智能厦门国际' in sheet_name:
        for col in df.columns:
            col_str = str(col).strip()
            if col_str == '交易日期':
                mapping['date'] = col
            elif col_str == '摘要':
                mapping['remark'] = col
            elif col_str == '转出':
                mapping['amount_out'] = col
            elif col_str == '转入':
                mapping['amount_in'] = col
            elif col_str == '对方户名':
                mapping['counterparty'] = col
            elif col_str == '币种':
                mapping['currency'] = col
        if mapping['date'] and (mapping['amount_in'] or mapping['amount_out']) and mapping['counterparty']:
            return mapping

    # 通用匹配（增强建设银行列名支持）
    for col in df.columns:
        low = normalize_column_name(str(col))
        # 日期列
        if not mapping['date'] and any(kw in low for kw in ['交易时间', '交易日', '日期', '记账日期', '交易日期', '起息日']):
            mapping['date'] = col
        if not mapping['trans_date'] and ('交易日期' in low or 'transactiondate' in low):
            mapping['trans_date'] = col
        if not mapping['trans_time'] and ('交易时间' in low or 'transactiontime' in low):
            mapping['trans_time'] = col
        # 对手方列（支持“对方户名”、“对方单位名称”等）
        if not mapping['counterparty']:
            if '对方户名' in low or '对方单位名称' in low or '收(付)方名称' in low or '对方账户名称' in low or '对方户名' in low:
                mapping['counterparty'] = col
        if not mapping['counterparty'] and any(kw in low for kw in ['对手方户名', '对方单位']):
            mapping['counterparty'] = col
        # 币种列
        if not mapping['currency'] and any(kw in low for kw in ['币种', '交易货币', '货币']):
            mapping['currency'] = col
        # 摘要/备注
        if not mapping['remark'] and any(kw in low for kw in ['摘要', '备注', '交易描述']):
            mapping['remark'] = col
        if not mapping['purpose'] and any(kw in low for kw in ['用途', '附言']):
            mapping['purpose'] = col
        # 借贷标志
        if not mapping['sign'] and any(kw in low for kw in ['借贷标志', '收支标志', '借/贷', 'direction']):
            mapping['sign'] = col
        # 交易类型
        if not mapping['trans_type'] and any(kw in low for kw in ['交易类型', '业务类型']):
            mapping['trans_type'] = col
        # 收入金额（贷方发生额）—— 增强：支持“贷方发生额/元(收入)”等变体
        if not mapping['amount_in']:
            if any(kw in low for kw in ['贷方发生额', '贷方金额', '收入', '贷方', '收入金额', '贷方发生额（收入）', '转入']):
                mapping['amount_in'] = col
            # 专门针对建设银行：列名包含“贷方发生额”和“收入”
            if '贷方发生额' in low and ('收入' in low or '贷方' in low):
                mapping['amount_in'] = col
        # 支出金额（借方发生额）
        if not mapping['amount_out']:
            if any(kw in low for kw in ['借方发生额', '借方金额', '支出', '借方', '支出金额', '借方发生额（支取）', '转出']):
                mapping['amount_out'] = col
            if '借方发生额' in low and ('支出' in low or '支取' in low):
                mapping['amount_out'] = col
        # 交易金额列
        if not mapping['amount'] and any(kw in low for kw in ['交易金额', '发生额', '金额']):
            mapping['amount'] = col
        # 付款人/收款人
        if not mapping['payer_name'] and any(kw in low for kw in ['付款人名称', '付款方名称']):
            mapping['payer_name'] = col
        if not mapping['payee_name'] and any(kw in low for kw in ['收款人名称', '收款方名称']):
            mapping['payee_name'] = col

    # 若仍未找到收入/支出列，尝试精确匹配常见列名
    if not mapping['amount_in']:
        for col in df.columns:
            col_str = str(col).strip()
            if col_str in ('收入', '收入金额', '转入', '贷方发生额', '贷方发生额/元(收入)'):
                mapping['amount_in'] = col
                break
    if not mapping['amount_out']:
        for col in df.columns:
            col_str = str(col).strip()
            if col_str in ('支出', '支出金额', '转出', '借方发生额', '借方发生额/元(支取)'):
                mapping['amount_out'] = col
                break

    if '中行' in sheet_name:
        if not mapping['payer_name']:
            for col in df.columns:
                if '付款人' in str(col):
                    mapping['payer_name'] = col
                    break
        if not mapping['payee_name']:
            for col in df.columns:
                if '收款人' in str(col):
                    mapping['payee_name'] = col
                    break
        if not mapping['amount'] and not mapping['amount_in'] and not mapping['amount_out']:
            for col in df.columns:
                if '交易金额' in str(col) or 'Trade Amount' in str(col):
                    mapping['amount'] = col
                    break
    return mapping

def parse_sheet(df, sheet_name, mapping, sheet_currency=None):
    records = []
    date_col = mapping.get('date')
    curr_col = mapping.get('currency')
    remark_col = mapping.get('remark')
    purpose_col = mapping.get('purpose')
    trans_type_col = mapping.get('trans_type')
    payer_col = mapping.get('payer_name')
    payee_col = mapping.get('payee_name')
    cp_col = mapping.get('counterparty')
    trans_date_col = mapping.get('trans_date')
    trans_time_col = mapping.get('trans_time')

    if not date_col:
        return records

    inferred_currency = None
    if '欧元' in sheet_name:
        inferred_currency = 'EUR'
    elif '美元' in sheet_name:
        inferred_currency = 'USD'
    elif '港币' in sheet_name:
        inferred_currency = 'HKD'
    elif '英镑' in sheet_name:
        inferred_currency = 'GBP'
    if sheet_currency:
        inferred_currency = sheet_currency

    for idx, row in df.iterrows():
        try:
            trans_datetime = None
            if trans_date_col and trans_time_col:
                date_val = row.get(trans_date_col) if trans_date_col in df.columns else None
                time_val = row.get(trans_time_col) if trans_time_col in df.columns else None
                if pd.notna(date_val) and pd.notna(time_val):
                    try:
                        if isinstance(date_val, (int, float)):
                            date_str = str(int(date_val))
                            if len(date_str) == 8 and date_str.isdigit():
                                date_obj = datetime.strptime(date_str, '%Y%m%d').date()
                            else:
                                date_obj = (datetime(1899, 12, 30) + pd.Timedelta(days=int(date_val))).date()
                        else:
                            date_obj = pd.to_datetime(date_val).date()
                        if isinstance(time_val, (int, float)):
                            time_str = str(int(time_val)).zfill(6)
                            if len(time_str) == 6 and time_str.isdigit():
                                time_obj = datetime.strptime(time_str, '%H%M%S').time()
                            else:
                                time_obj = datetime.strptime(str(time_val).split('.')[0], '%H:%M:%S').time()
                        elif isinstance(time_val, str):
                            if ':' in time_val:
                                time_obj = datetime.strptime(time_val.split('.')[0], '%H:%M:%S').time()
                            else:
                                time_str = time_val.zfill(6)
                                time_obj = datetime.strptime(time_str, '%H%M%S').time()
                        else:
                            time_obj = datetime.strptime(str(time_val).split('.')[0], '%H:%M:%S').time()
                        trans_datetime = datetime.combine(date_obj, time_obj)
                    except:
                        pass

            if trans_datetime is None:
                date_val = row.get(date_col)
                parsed_date = parse_date_cell(date_val)
                if parsed_date is None:
                    continue
                trans_datetime = datetime.combine(parsed_date, datetime.min.time())

            amount = 0.0
            direction = None

            in_col = mapping.get('amount_in')
            out_col = mapping.get('amount_out')
            if in_col and in_col in df.columns:
                amt = safe_float_convert(row[in_col])
                if amt > 0:
                    amount = amt
                    direction = 'in'
            if amount == 0 and out_col and out_col in df.columns:
                amt = safe_float_convert(row[out_col])
                if amt > 0:
                    amount = amt
                    direction = 'out'

            if amount == 0:
                amount_col = mapping.get('amount')
                if amount_col and amount_col in df.columns:
                    amt = safe_float_convert(row[amount_col])
                    if amt > 0:
                        amount = amt
                        direction = 'in'
                    elif amt < 0:
                        amount = -amt
                        direction = 'out'

            if amount > 0 and direction is None and trans_type_col and trans_type_col in df.columns:
                trans_type = str(row[trans_type_col]).strip()
                if trans_type in ('往账', '支出', '付款', 'debit', '借方'):
                    direction = 'out'
                elif trans_type in ('来账', '收入', '收款', 'credit', '贷方'):
                    direction = 'in'

            if amount == 0 or direction is None:
                continue

            counterparty = ''
            if cp_col and cp_col in df.columns and pd.notna(row[cp_col]):
                candidate = str(row[cp_col]).strip()
                if candidate not in ('', 'nan', 'None'):
                    counterparty = candidate
            if not counterparty and direction == 'in' and payer_col and payer_col in df.columns and pd.notna(row[payer_col]):
                counterparty = str(row[payer_col]).strip()
            if not counterparty and direction == 'out' and payee_col and payee_col in df.columns and pd.notna(row[payee_col]):
                counterparty = str(row[payee_col]).strip()
            if not counterparty:
                for col in df.columns:
                    if '对方账户名称' in str(col) or '对方户名' in str(col):
                        val = row.get(col)
                        if pd.notna(val) and str(val).strip() not in ('', 'nan', 'None'):
                            counterparty = str(val).strip()
                            break

            if not counterparty:
                continue

            currency = 'CNY'
            if curr_col and curr_col in df.columns and pd.notna(row[curr_col]):
                curr = str(row[curr_col]).strip()
                if curr in ['人民币元', '人民币', 'CNY', 'RMB']:
                    currency = 'CNY'
                elif curr in ['美元', 'USD']:
                    currency = 'USD'
                elif curr in ['欧元', 'EUR']:
                    currency = 'EUR'
                elif curr in ['港币', 'HKD']:
                    currency = 'HKD'
                else:
                    currency = curr.upper()
            elif inferred_currency:
                currency = inferred_currency

            remark = ''
            if remark_col and remark_col in df.columns and pd.notna(row[remark_col]):
                remark = str(row[remark_col])
            purpose = ''
            if purpose_col and purpose_col in df.columns and pd.notna(row[purpose_col]):
                purpose = str(row[purpose_col])
            if '附言' in df.columns and pd.notna(row['附言']):
                purpose += ' ' + str(row['附言'])

            records.append({
                'date': trans_datetime,
                'amount': amount,
                'direction': direction,
                'counterparty': counterparty,
                'currency': currency,
                'remark': remark,
                'purpose': purpose,
                'original_sheet': sheet_name
            })
        except Exception as e:
            st.warning(f"跳过 {sheet_name} 第 {idx} 行，解析失败: {e}")
            continue
    return records

def load_all_transactions(uploaded_files):
    all_trans = []
    internal_companies = [
        '珠海市广通客车有限公司', '中兴智能汽车有限公司',
        '深圳金兴通汽车销售有限公司', '广州金兴通汽车销售有限公司',
        '中兴通讯集团财务有限公司'
    ]
    debug_info = []
    for file in uploaded_files:
        filename = file.name
        if filename.endswith('.xls') and not filename.endswith('.xlsx'):
            engine = 'xlrd'
        else:
            engine = 'openpyxl'
        try:
            xls = pd.ExcelFile(file, engine=engine)
        except Exception as e:
            st.error(f"无法读取文件 {filename}: {e}")
            continue

        for sheet_name in xls.sheet_names:
            if any(kw in sheet_name.lower() for kw in ['保证金', '汇总', '合计', 'balance']):
                continue
            try:
                df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
                if df_raw.empty:
                    continue
                header_row = None
                sheet_currency = None

                # 意大利子公司特殊处理
                if '意大利子公司' in sheet_name or 'ZONSON SMART AUTO ITALIA' in sheet_name or '意大利' in sheet_name:
                    debug_info.append(f"🔍 {file.name} - {sheet_name}: 使用意大利子公司专用解析器")
                    # 正确获取币种（第3行第2列，索引2,1）
                    if len(df_raw) > 2:
                        currency_cell = str(df_raw.iloc[2, 1]).strip()  # 修正：第3行第2列
                        if currency_cell == '欧元':
                            sheet_currency = 'EUR'
                        elif currency_cell == '美元':
                            sheet_currency = 'USD'
                        elif currency_cell == '港币':
                            sheet_currency = 'HKD'
                    # 表头在第4行（索引3）
                    if len(df_raw) > 3:
                        header_row = 3
                    else:
                        header_row = None
                    if header_row is not None:
                        df_data = pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
                        if not df_data.empty:
                            mapping = {
                                'date': '交易日期' if '交易日期' in df_data.columns else None,
                                'amount': '交易金额' if '交易金额' in df_data.columns else None,
                                'counterparty': '对方账户名称' if '对方账户名称' in df_data.columns else None,
                                'currency': '交易币种' if '交易币种' in df_data.columns else None,
                            }
                            # 位置备用
                            if mapping['date'] is None and len(df_data.columns) > 5:
                                mapping['date'] = df_data.columns[5]
                            if mapping['amount'] is None and len(df_data.columns) > 3:
                                mapping['amount'] = df_data.columns[3]
                            if mapping['counterparty'] is None and len(df_data.columns) > 8:
                                mapping['counterparty'] = df_data.columns[8]
                            if mapping['currency'] is None and len(df_data.columns) > 2:
                                mapping['currency'] = df_data.columns[2]
                            records = parse_sheet(df_data, sheet_name, mapping, sheet_currency=sheet_currency)
                            filtered = [r for r in records if r['counterparty'] not in internal_companies]
                            all_trans.extend(filtered)
                            if filtered:
                                st.success(f"✓ {file.name} - {sheet_name}: {len(filtered)} 条记录")
                                sample = filtered[0]
                                debug_info.append(f"📄 {file.name}/{sheet_name} 示例: {sample['direction']} {sample['counterparty'][:30]} {sample['amount']} {sample['currency']} 日期:{sample['date']}")
                            else:
                                st.info(f"ℹ️ {file.name} - {sheet_name}: 解析到0条有效外部交易")
                                debug_info.append(f"🔍 {file.name}/{sheet_name} 映射: date={mapping['date']}, amount={mapping['amount']}, counterparty={mapping['counterparty']}, currency={mapping['currency']}, sheet_currency={sheet_currency}")
                                if len(df_data) > 0:
                                    sample_rows = df_data.head(3).iloc[:, :5].to_string()
                                    debug_info.append(f"   前3行数据示例:\n{sample_rows}")
                            continue

                # 建设银行工作表特殊处理：尝试直接查找包含“交易时间”和“贷方发生额”的行作为表头
                if '建行' in sheet_name or '建设银行' in sheet_name:
                    # 手动查找表头行
                    found_header = None
                    for i in range(min(30, len(df_raw))):
                        row_cells = [str(cell).strip() for cell in df_raw.iloc[i]]
                        # 检查是否同时包含“交易时间”和“贷方发生额”
                        if any('交易时间' in cell for cell in row_cells) and any('贷方发生额' in cell for cell in row_cells):
                            found_header = i
                            break
                    if found_header is not None:
                        header_row = found_header
                        debug_info.append(f"✅ {file.name} - {sheet_name}: 建设银行专用表头行索引 = {header_row}")
                    else:
                        # 回退到通用查找
                        header_row = find_header_row(df_raw)

                # 华夏银行
                elif '华夏' in sheet_name:
                    header_row = find_header_row_for_huaoxia(df_raw)
                else:
                    header_row = find_header_row(df_raw)

                if header_row is None:
                    debug_info.append(f"⚠️ {file.name} - {sheet_name}: 未找到表头行")
                    sample = df_raw.iloc[:20, :5].to_string()
                    debug_info.append(f"   前20行预览:\n{sample}")
                    continue

                debug_info.append(f"✅ {file.name} - {sheet_name}: 表头行索引 = {header_row}")
                header_content = df_raw.iloc[header_row, :10].to_string()
                debug_info.append(f"   表头内容: {header_content}")
                df_data = pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
                if df_data.empty:
                    continue

                mapping = identify_columns_enhanced(df_data, sheet_name)
                records = parse_sheet(df_data, sheet_name, mapping, sheet_currency=sheet_currency)
                filtered = [r for r in records if r['counterparty'] not in internal_companies]
                all_trans.extend(filtered)
                if filtered:
                    st.success(f"✓ {file.name} - {sheet_name}: {len(filtered)} 条记录")
                    sample = filtered[0]
                    debug_info.append(f"📄 {file.name}/{sheet_name} 示例: {sample['direction']} {sample['counterparty'][:30]} {sample['amount']} {sample['currency']} 日期:{sample['date']}")
                else:
                    st.info(f"ℹ️ {file.name} - {sheet_name}: 解析到0条有效外部交易")
                    debug_info.append(f"🔍 {file.name}/{sheet_name} 映射: date={mapping['date']}, counterparty={mapping['counterparty']}, amount_in={mapping['amount_in']}, amount_out={mapping['amount_out']}, amount={mapping['amount']}, currency={mapping['currency']}")
                    if len(df_data) > 0:
                        sample_rows = df_data.head(3).iloc[:, :5].to_string()
                        debug_info.append(f"   前3行数据示例:\n{sample_rows}")
            except Exception as e:
                st.error(f"解析失败 {file.name} - {sheet_name}: {str(e)}")
    with st.sidebar.expander("🔧 调试信息", expanded=False):
        for info in debug_info[:80]:
            st.text(info)
    return all_trans

def convert_to_cny(transactions, rates):
    for t in transactions:
        curr = t['currency']
        rate = rates.get(curr, 1.0)
        t['amount_cny'] = t['amount'] * rate
    return transactions

def get_top_counterparties(transactions, direction, top_n=20):
    filtered = [t for t in transactions if t['direction'] == direction and t['counterparty']]
    if not filtered:
        return [], pd.DataFrame()
    df = pd.DataFrame(filtered)
    summary = df.groupby(['counterparty', 'currency']).agg(
        合计金额=('amount', 'sum'),
        折合人民币=('amount_cny', 'sum')
    ).reset_index()
    total_by_company = summary.groupby('counterparty')['折合人民币'].sum().reset_index()
    total_by_company = total_by_company.sort_values('折合人民币', ascending=False).head(top_n)
    result = []
    for _, row in total_by_company.iterrows():
        company = row['counterparty']
        total_cny = row['折合人民币']
        currency_details = summary[summary['counterparty'] == company][['currency', '合计金额']].to_dict('records')
        result.append({
            '公司名称': company,
            '各币种合计': currency_details,
            '合计折合人民币(元)': total_cny
        })
    return result, summary

def main():
    st.markdown('<div class="main-header">🏦 银行流水智能分析平台</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">多银行格式自动适配 | 排除内部交易 | 收付款排名 | 明细追溯</div>', unsafe_allow_html=True)
    
    with st.sidebar:
        st.header("📂 数据上传")
        st.markdown("**支持的文件格式：** XLSX, XLS（每个文件不超过200MB）")
        uploaded_files = st.file_uploader("请选择银行流水Excel文件（可多选）", type=['xlsx', 'xls'], accept_multiple_files=True, label_visibility="collapsed")
        
        st.header("⚙️ 参数设置")
        analysis_date = st.date_input("选择汇率日期（按当天中间价折算）", value=datetime.now().date())
        date_str = analysis_date.strftime("%Y-%m-%d")
        
        rank_limit = st.number_input("收款方/付款方排名显示数量", min_value=1, max_value=500, value=20, step=1,
                                     help="设置排名前多少名，例如10、20、50。若需显示全部，可输入一个大于总交易对手方数量的大数字（如500）")
        
        if st.button("🚀 开始分析", use_container_width=True):
            if not uploaded_files:
                st.error("请至少上传一个文件")
                return
            with st.spinner("正在解析数据，请稍候..."):
                transactions = load_all_transactions(uploaded_files)
                if not transactions:
                    st.error("未解析到任何有效外部交易记录，请检查文件格式")
                    return
                rates = get_exchange_rates(date_str)
                st.sidebar.info(f"当前汇率 (CNY基准): USD={rates.get('USD',7.2)} EUR={rates.get('EUR',7.8)} HKD={rates.get('HKD',0.92)}")
                transactions = convert_to_cny(transactions, rates)
                st.session_state['transactions'] = transactions
                st.session_state['rates'] = rates
                st.session_state['rank_limit'] = rank_limit
                st.success(f"成功解析 {len(transactions)} 条外部交易记录")
        
        if 'transactions' not in st.session_state:
            st.info("请上传文件并点击「开始分析」")
            return
    
    transactions = st.session_state['transactions']
    rank_limit = st.session_state.get('rank_limit', 20)
    
    if transactions:
        min_date = min(t['date'] for t in transactions)
        max_date = max(t['date'] for t in transactions)
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("起始日期", min_date, min_value=min_date, max_value=max_date)
        with col2:
            end_date = st.date_input("结束日期", max_date, min_value=min_date, max_value=max_date)
        filtered = [t for t in transactions if start_date <= t['date'].date() <= end_date]
    else:
        filtered = transactions
    
    if not filtered:
        st.warning("当前筛选范围内无交易数据")
        return
    
    top_payees, _ = get_top_counterparties(filtered, 'in', top_n=rank_limit)
    top_payers, _ = get_top_counterparties(filtered, 'out', top_n=rank_limit)
    
    tab1, tab2, tab3 = st.tabs(["📥 收款方排名 (Top {})".format(rank_limit), "📤 付款方排名 (Top {})".format(rank_limit), "🔍 交易明细查询"])
    
    with tab1:
        if top_payees:
            st.subheader(f"收款方排名（按折合人民币合计金额，前{rank_limit}名）")
            for idx, company_info in enumerate(top_payees, 1):
                company = company_info['公司名称']
                total_cny = company_info['合计折合人民币(元)']
                currency_details = company_info['各币种合计']
                detail_str = ", ".join([f"{d['currency']}: {d['合计金额']:,.2f}" for d in currency_details])
                with st.container():
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.markdown(f"**{idx}. {company}**  —  {detail_str}")
                    with col_b:
                        st.markdown(f"💰 合计折合人民币: **¥{total_cny:,.2f}**")
                    if st.button(f"查看 {company} 收款明细", key=f"payee_{company}_{idx}"):
                        st.session_state['selected_company'] = company
                        st.session_state['selected_direction'] = 'in'
        else:
            st.info("无收款记录")
    
    with tab2:
        if top_payers:
            st.subheader(f"付款方排名（按折合人民币合计金额，前{rank_limit}名）")
            for idx, company_info in enumerate(top_payers, 1):
                company = company_info['公司名称']
                total_cny = company_info['合计折合人民币(元)']
                currency_details = company_info['各币种合计']
                detail_str = ", ".join([f"{d['currency']}: {d['合计金额']:,.2f}" for d in currency_details])
                with st.container():
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.markdown(f"**{idx}. {company}**  —  {detail_str}")
                    with col_b:
                        st.markdown(f"💰 合计折合人民币: **¥{total_cny:,.2f}**")
                    if st.button(f"查看 {company} 付款明细", key=f"payer_{company}_{idx}"):
                        st.session_state['selected_company'] = company
                        st.session_state['selected_direction'] = 'out'
        else:
            st.info("无付款记录")
    
    with tab3:
        st.subheader("按公司名称搜索交易明细")
        search_term = st.text_input("输入对方公司名称关键词（模糊匹配）")
        if search_term:
            search_results = [t for t in filtered if search_term.lower() in t['counterparty'].lower()]
            if search_results:
                df_search = pd.DataFrame(search_results)
                df_search['date'] = pd.to_datetime(df_search['date']).dt.strftime('%Y-%m-%d %H:%M:%S')
                df_search['direction'] = df_search['direction'].map({'in': '收款', 'out': '付款'})
                display_df = df_search.rename(columns={
                    'date': '交易日期',
                    'direction': '交易方向',
                    'counterparty': '对方公司',
                    'amount': '交易金额',
                    'currency': '币种',
                    'amount_cny': '折合人民币(元)',
                    'remark': '摘要',
                    'purpose': '用途/附言',
                    'original_sheet': '来源工作表'
                })
                total_cny = df_search['amount_cny'].sum()
                st.markdown(f"**合计折合人民币: ¥{total_cny:,.2f}**")
                st.dataframe(display_df[['交易日期', '交易方向', '对方公司', '交易金额', '币种', '折合人民币(元)', '摘要', '用途/附言', '来源工作表']], use_container_width=True)
            else:
                st.info("未找到匹配记录")
    
    if 'selected_company' in st.session_state and st.session_state['selected_company']:
        company = st.session_state['selected_company']
        direction = st.session_state['selected_direction']
        dir_text = "收款" if direction == 'in' else "付款"
        st.subheader(f"📋 {company} 的{dir_text}明细")
        details = [t for t in filtered if t['counterparty'] == company and t['direction'] == direction]
        if details:
            df_details = pd.DataFrame(details)
            df_details['date'] = pd.to_datetime(df_details['date']).dt.strftime('%Y-%m-%d %H:%M:%S')
            df_details['amount_cny'] = df_details['amount_cny'].apply(lambda x: f"{x:,.2f}")
            df_details['amount'] = df_details['amount'].apply(lambda x: f"{x:,.2f}")
            display_df = df_details.rename(columns={
                'date': '交易日期',
                'amount': '交易金额',
                'currency': '币种',
                'amount_cny': '折合人民币(元)',
                'remark': '摘要',
                'purpose': '用途/附言',
                'original_sheet': '来源工作表'
            })
            st.dataframe(display_df[['交易日期', '交易金额', '币种', '折合人民币(元)', '摘要', '用途/附言', '来源工作表']], use_container_width=True)
        else:
            st.info("无明细数据")
    
    st.sidebar.header("💾 下载分析报告")
    if st.sidebar.button("生成并下载完整报告", use_container_width=True):
        report_data = []
        for t in filtered:
            report_data.append({
                '交易日期': t['date'].strftime('%Y-%m-%d %H:%M:%S'),
                '交易方向': '收款' if t['direction'] == 'in' else '付款',
                '对方公司': t['counterparty'],
                '交易金额': t['amount'],
                '币种': t['currency'],
                '折合人民币': t['amount_cny'],
                '摘要': t['remark'],
                '用途/附言': t['purpose'],
                '来源工作表': t['original_sheet']
            })
        df_report = pd.DataFrame(report_data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_report.to_excel(writer, sheet_name='所有交易明细', index=False)
            if top_payees:
                in_rank = []
                for i, ci in enumerate(top_payees, 1):
                    in_rank.append({
                        '排名': i,
                        '公司名称': ci['公司名称'],
                        '各币种合计': str(ci['各币种合计']),
                        '合计折合人民币(元)': ci['合计折合人民币(元)']
                    })
                pd.DataFrame(in_rank).to_excel(writer, sheet_name='收款方排名', index=False)
            if top_payers:
                out_rank = []
                for i, ci in enumerate(top_payers, 1):
                    out_rank.append({
                        '排名': i,
                        '公司名称': ci['公司名称'],
                        '各币种合计': str(ci['各币种合计']),
                        '合计折合人民币(元)': ci['合计折合人民币(元)']
                    })
                pd.DataFrame(out_rank).to_excel(writer, sheet_name='付款方排名', index=False)
        st.sidebar.download_button(
            label="📥 下载 Excel 报告",
            data=output.getvalue(),
            file_name=f"银行流水分析报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

if __name__ == "__main__":
    main()
