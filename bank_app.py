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
    """将各种格式的日期值转换为 datetime.date 对象（非中行时使用）"""
    if pd.isna(val):
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date()
    if isinstance(val, (int, float)):
        # 如果是 8 位数字（如 20260313），按 YYYYMMDD 解析
        if 19000101 <= int(val) <= 21001231:
            return datetime.strptime(str(int(val)), '%Y%m%d').date()
        else:
            # 否则当作 Excel 序列号处理
            try:
                return (datetime(1899, 12, 30) + pd.Timedelta(days=int(val))).date()
            except:
                return None
    if isinstance(val, str):
        date_part = val.split()[0] if ' ' in val else val
        for fmt in ('%Y%m%d', '%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(date_part, fmt).date()
            except:
                continue
        try:
            return pd.to_datetime(val).date()
        except:
            return None
    return None

def find_header_row(df, max_rows=30):
    keywords = ['交易时间', '交易日', '日期', '记账日期', '交易日期', '起息日',
                '对方户名', '对方单位名称', '对方账号', '收款人名称', '付款人名称',
                '贷方发生额', '借方发生额', '贷方金额', '借方金额', '收入', '支出',
                '币种', '交易货币', '摘要', '附言', '用途', '借贷标志', '收支标志',
                '交易类型', '业务类型']
    for i in range(min(max_rows, len(df))):
        row = df.iloc[i].astype(str).str.lower()
        match_count = sum(1 for kw in keywords if any(kw in cell for cell in row))
        if match_count >= 2:
            return i
    return None

def normalize_column_name(col):
    if not isinstance(col, str):
        return ''
    col = col.strip().replace(' ', '').replace('　', '')
    col = col.translate(str.maketrans('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    col = col.translate(str.maketrans('ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ', 'abcdefghijklmnopqrstuvwxyz'))
    return col.lower()

def identify_columns_enhanced(df, sheet_name):
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
    for col in df.columns:
        low = normalize_column_name(str(col))
        if not mapping['date'] and any(kw in low for kw in ['交易时间', '交易日', '日期', '记账日期', '交易日期', '起息日']):
            mapping['date'] = col
        # 专门识别“交易日期”和“交易时间”
        if not mapping['trans_date'] and ('交易日期' in low or 'transactiondate' in low):
            mapping['trans_date'] = col
        if not mapping['trans_time'] and ('交易时间' in low or 'transactiontime' in low):
            mapping['trans_time'] = col
        if not mapping['counterparty'] and any(kw in low for kw in ['对方户名', '对方单位名称', '收(付)方名称', '对方账户名称', '对手方户名', '对方单位']):
            mapping['counterparty'] = col
        if not mapping['currency'] and any(kw in low for kw in ['币种', '交易货币', '货币']):
            mapping['currency'] = col
        if not mapping['remark'] and any(kw in low for kw in ['摘要', '备注', '交易描述']):
            mapping['remark'] = col
        if not mapping['purpose'] and any(kw in low for kw in ['用途', '附言']):
            mapping['purpose'] = col
        if not mapping['sign'] and any(kw in low for kw in ['借贷标志', '收支标志', '借/贷', 'direction']):
            mapping['sign'] = col
        if not mapping['trans_type'] and any(kw in low for kw in ['交易类型', '业务类型']):
            mapping['trans_type'] = col
        if not mapping['amount_in'] and any(kw in low for kw in ['贷方发生额', '贷方金额', '收入', '贷方', '收入金额', '贷方发生额（收入）']):
            mapping['amount_in'] = col
        if not mapping['amount_out'] and any(kw in low for kw in ['借方发生额', '借方金额', '支出', '借方', '支出金额', '借方发生额（支取）']):
            mapping['amount_out'] = col
        if not mapping['amount'] and any(kw in low for kw in ['交易金额', '发生额', '金额']):
            mapping['amount'] = col
        if not mapping['payer_name'] and any(kw in low for kw in ['付款人名称', '付款方名称']):
            mapping['payer_name'] = col
        if not mapping['payee_name'] and any(kw in low for kw in ['收款人名称', '收款方名称']):
            mapping['payee_name'] = col

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

def parse_sheet(df, sheet_name, mapping):
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

    for idx, row in df.iterrows():
        # ---------- 日期时间解析（针对中国银行特殊处理）----------
        trans_datetime = None
        if '中行' in sheet_name and trans_date_col and trans_time_col:
            date_val = row.get(trans_date_col)
            time_val = row.get(trans_time_col)
            if pd.notna(date_val) and pd.notna(time_val):
                try:
                    # 处理日期：可能是整数 20260313 或字符串 "20260313"
                    if isinstance(date_val, (int, float)):
                        date_str = str(int(date_val))
                        if len(date_str) == 8 and date_str.isdigit():
                            date_obj = datetime.strptime(date_str, '%Y%m%d').date()
                        else:
                            # 回退到 Excel 序列号
                            date_obj = (datetime(1899, 12, 30) + pd.Timedelta(days=int(date_val))).date()
                    else:
                        date_obj = pd.to_datetime(date_val).date()
                    # 处理时间：可能是整数 143802 或字符串 "14:38:02"
                    if isinstance(time_val, (int, float)):
                        time_str = str(int(time_val)).zfill(6)  # 补齐6位
                        if len(time_str) == 6 and time_str.isdigit():
                            time_obj = datetime.strptime(time_str, '%H%M%S').time()
                        else:
                            time_obj = datetime.strptime(str(time_val).split('.')[0], '%H:%M:%S').time()
                    elif isinstance(time_val, str):
                        if ':' in time_val:
                            time_obj = datetime.strptime(time_val.split('.')[0], '%H:%M:%S').time()
                        else:
                            # 纯数字字符串如 "143802"
                            time_str = time_val.zfill(6)
                            time_obj = datetime.strptime(time_str, '%H%M%S').time()
                    else:
                        time_obj = datetime.strptime(str(time_val).split('.')[0], '%H:%M:%S').time()
                    trans_datetime = datetime.combine(date_obj, time_obj)
                except Exception as e:
                    # 组合失败，回退到原逻辑
                    pass

        # 如果中行组合失败或非中行，使用原有单列日期解析
        if trans_datetime is None:
            date_val = row.get(date_col)
            parsed_date = parse_date_cell(date_val)
            if parsed_date is None:
                continue
            trans_datetime = datetime.combine(parsed_date, datetime.min.time())

        # ---------- 金额和方向 ----------
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
            if trans_type in ('往账', '支出', '付款', 'debit'):
                direction = 'out'
            elif trans_type in ('来账', '收入', '收款', 'credit'):
                direction = 'in'

        if amount == 0 or direction is None:
            continue

        # ---------- 对方名称 ----------
        counterparty = ''
        if direction == 'out' and payee_col and payee_col in df.columns and pd.notna(row[payee_col]):
            counterparty = str(row[payee_col]).strip()
        elif direction == 'in' and payer_col and payer_col in df.columns and pd.notna(row[payer_col]):
            counterparty = str(row[payer_col]).strip()

        if not counterparty and cp_col and cp_col in df.columns and pd.notna(row[cp_col]):
            candidate = str(row[cp_col]).strip()
            if candidate not in ('', 'nan', 'None', '对公往来账户', '对公信贷-DPS系统间往来'):
                counterparty = candidate

        if not counterparty and direction == 'out' and payee_col and payee_col in df.columns:
            counterparty = str(row[payee_col]).strip()
        if not counterparty and direction == 'in' and payer_col and payer_col in df.columns:
            counterparty = str(row[payer_col]).strip()

        if not counterparty:
            continue

        # ---------- 币种 ----------
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
        xls = pd.ExcelFile(file)
        for sheet_name in xls.sheet_names:
            if any(kw in sheet_name.lower() for kw in ['保证金', '汇总', '合计', 'balance']):
                continue
            try:
                df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
                if df_raw.empty:
                    continue
                header_row = find_header_row(df_raw)
                if header_row is None:
                    debug_info.append(f"⚠️ {file.name} - {sheet_name}: 未找到表头行")
                    continue
                df_data = pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
                if df_data.empty:
                    continue
                mapping = identify_columns_enhanced(df_data, sheet_name)
                records = parse_sheet(df_data, sheet_name, mapping)
                filtered = [r for r in records if r['counterparty'] not in internal_companies]
                all_trans.extend(filtered)
                if filtered:
                    st.success(f"✓ {file.name} - {sheet_name}: {len(filtered)} 条记录")
                    sample = filtered[0]
                    debug_info.append(f"📄 {file.name}/{sheet_name} 示例: {sample['direction']} {sample['counterparty'][:30]} {sample['amount']} {sample['currency']} 日期:{sample['date']}")
                else:
                    st.info(f"ℹ️ {file.name} - {sheet_name}: 解析到0条有效外部交易")
                    debug_info.append(f"🔍 {file.name}/{sheet_name} 映射: date={mapping['date']}, payer={mapping['payer_name']}, payee={mapping['payee_name']}, amount={mapping['amount']}")
            except Exception as e:
                st.error(f"解析失败 {file.name} - {sheet_name}: {str(e)}")
    with st.sidebar.expander("🔧 调试信息", expanded=False):
        for info in debug_info[:30]:
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