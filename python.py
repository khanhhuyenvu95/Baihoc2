import streamlit as st
import pandas as pd
import numpy as np
import json
from google import genai
from google.genai.errors import APIError
from typing import Dict, Any, Optional
# Cần cài đặt thư viện python-docx để đọc file .docx: pip install python-docx
# Do hạn chế về môi trường, chúng ta sẽ hướng dẫn người dùng cài đặt
# và sử dụng thư viện này để trích xuất văn bản từ file Word.
try:
    from docx import Document
except ImportError:
    st.warning("⚠️ Vui lòng chạy lệnh 'pip install python-docx' để Streamlit có thể đọc nội dung file Word.")

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="Ứng dụng Đánh giá Phương án Kinh doanh",
    layout="wide"
)

st.title("Ứng dụng Đánh giá Phương án Đầu tư Dự án 📊")
st.caption("Sử dụng Gemini AI để trích xuất dữ liệu tài chính từ file Word và phân tích hiệu quả dự án.")

# Khóa API
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")

# --- Hàm 1: Trích xuất Dữ liệu Tài chính bằng AI ---
def extract_financial_data(file_buffer: bytes, api_key: str) -> Optional[Dict[str, Any]]:
    """Đọc file Word, trích xuất văn bản và gửi đến Gemini để lọc dữ liệu theo cấu trúc JSON."""
    try:
        # 1. Đọc nội dung file Word
        with open("temp_upload.docx", "wb") as f:
            f.write(file_buffer)
        
        doc = Document("temp_upload.docx")
        text_content = "\n".join([paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()])
        
        if not text_content:
            st.error("Nội dung file Word trống. Vui lòng kiểm tra file.")
            return None

        # 2. Cấu hình AI Client và Model
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'

        # 3. Định nghĩa Yêu cầu và Schema JSON
        system_prompt = (
            "Bạn là trợ lý trích xuất dữ liệu tài chính. Nhiệm vụ của bạn là đọc kỹ văn bản được cung cấp "
            "và trích xuất 6 thông số tài chính chính xác nhất. Đơn vị trong văn bản là tỷ đồng (nếu có), "
            "hãy chuyển chúng thành số thập phân. WACC và Thuế suất phải là số thập phân (ví dụ: 0.13 hoặc 0.2)."
        )

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "vốn_đầu_tư": {"type": "NUMBER", "description": "Tổng Vốn đầu tư ban đầu (VND, số thập phân)"},
                "vòng_đời_dự_án": {"type": "INTEGER", "description": "Vòng đời dự án (số năm)"},
                "doanh_thu_hàng_năm": {"type": "NUMBER", "description": "Doanh thu cố định hàng năm (VND, số thập phân)"},
                "chi_phí_hàng_năm": {"type": "NUMBER", "description": "Chi phí hoạt động cố định hàng năm (VND, số thập phân)"},
                "wacc": {"type": "NUMBER", "description": "Chi phí vốn bình quân (WACC), dưới dạng số thập phân (ví dụ: 0.13 cho 13%)"},
                "thuế_suất": {"type": "NUMBER", "description": "Thuế suất thu nhập doanh nghiệp, dưới dạng số thập phân (ví dụ: 0.2 cho 20%)"}
            },
            "required": ["vốn_đầu_tư", "vòng_đời_dự_án", "doanh_thu_hàng_năm", "chi_phí_hàng_năm", "wacc", "thuế_suất"]
        }

        user_query = f"Trích xuất các thông số tài chính từ văn bản sau và trả về dưới dạng JSON:\n\n---\n\n{text_content}"
        
        # 4. Gọi API
        response = client.models.generate_content(
            model=model_name,
            contents=user_query,
            system_instruction=types.SystemInstruction(parts=[types.Part.from_text(system_prompt)]),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema
            )
        )
        
        # 5. Phân tích kết quả
        json_string = response.text.strip()
        data = json.loads(json_string)
        
        # Chuyển đổi đơn vị (Giả định đầu vào file là Tỷ VND, chuyển về VND)
        # Nếu đã yêu cầu AI trả về số nguyên VND, bước này không cần.
        # Giữ nguyên giá trị AI trích xuất (thường là đơn vị nhỏ nhất, vd: VND)
        return data

    except APIError as e:
        st.error(f"Lỗi gọi Gemini API: {e}. Vui lòng kiểm tra Khóa API.")
        return None
    except Exception as e:
        st.error(f"Lỗi khi trích xuất hoặc phân tích JSON: {e}")
        st.info("Kiểm tra lại định dạng và nội dung file Word, đảm bảo các số liệu rõ ràng.")
        return None

# --- Hàm 2 & 3: Xây dựng Bảng Dòng Tiền và Tính Chỉ số ---
@st.cache_data(show_spinner=False)
def calculate_financial_metrics(data: Dict[str, float]) -> Dict[str, Any]:
    """Xây dựng bảng dòng tiền và tính NPV, IRR, PP, DPP."""
    I0 = data['vốn_đầu_tư']
    N = int(data['vòng_đời_dự_án'])
    R = data['doanh_thu_hàng_năm']
    C = data['chi_phí_hàng_năm']
    WACC = data['wacc']
    Tau = data['thuế_suất']

    # 1. Tính toán cơ bản
    EBIT = R - C
    Khau_hao = I0 / N # Giả định khấu hao đều, giá trị thanh lý = 0
    
    # Dòng tiền thuần hàng năm (NCF)
    EAT = EBIT * (1 - Tau)
    NCF_annual = EAT + Khau_hao

    # 2. Xây dựng Bảng Dòng Tiền (Cash Flow Table)
    years = list(range(0, N + 1))
    
    # Dòng tiền ra ban đầu (Năm 0)
    CF_list = [-I0]
    
    # Dòng tiền vào hàng năm (Năm 1 đến N)
    NCF_list = [NCF_annual] * N
    CF_list.extend(NCF_list) 

    # Hệ số chiết khấu (Discount Factor)
    Discount_factors = [1 / ((1 + WACC) ** t) for t in years]

    # Dòng tiền chiết khấu (Discounted Cash Flow - DCF)
    DCF_list = [CF_list[t] * Discount_factors[t] for t in years]

    # Dòng tiền tích lũy (Cumulative Cash Flow - CCF)
    CCF_list = np.cumsum(CF_list).tolist()
    
    # Dòng tiền chiết khấu tích lũy (Cumulative Discounted Cash Flow - CDCF)
    CDCF_list = np.cumsum(DCF_list).tolist()

    # Tạo DataFrame
    df_cf = pd.DataFrame({
        'Năm': years,
        'Dòng tiền (CF)': CF_list,
        'Hệ số chiết khấu': Discount_factors,
        'Dòng tiền chiết khấu (DCF)': DCF_list,
        'Dòng tiền tích lũy (CCF)': CCF_list,
        'Dòng tiền chiết khấu tích lũy (CDCF)': CDCF_list,
    })

    # 3. Tính Chỉ số Đánh giá
    
    # NPV (Giá trị hiện tại thuần)
    # np.npv yêu cầu suất chiết khấu và danh sách dòng tiền từ năm 1 trở đi.
    NPV = np.npv(WACC, NCF_list) + CF_list[0] 

    # IRR (Tỷ suất hoàn vốn nội bộ)
    IRR = np.irr(CF_list) 

    # PP (Thời gian hoàn vốn)
    # Tìm năm cuối cùng CCF < 0
    payback_year = next((i - 1 for i, ccf in enumerate(CCF_list) if ccf > 0), N)
    
    if payback_year < N and NCF_list[0] != 0:
        PP = payback_year + abs(CCF_list[payback_year]) / NCF_list[0]
    else:
        PP = float('inf') # Dự án không hoàn vốn trong vòng đời

    # DPP (Thời gian hoàn vốn có chiết khấu)
    # Tương tự PP, sử dụng CDCF
    discounted_payback_year = next((i - 1 for i, cdcf in enumerate(CDCF_list) if cdcf > 0), N)
    
    if discounted_payback_year < N and DCF_list[discounted_payback_year + 1] != 0:
        DPP = discounted_payback_year + abs(CDCF_list[discounted_payback_year]) / DCF_list[discounted_payback_year + 1]
    else:
        DPP = float('inf')

    # 4. Kết quả
    results = {
        'df_cf': df_cf,
        'NPV': NPV,
        'IRR': IRR,
        'PP': PP,
        'DPP': DPP,
        'WACC': WACC,
        'N': N
    }
    return results

# --- Hàm 4: Phân tích Chỉ số bằng AI ---
def get_ai_analysis_metrics(analysis_data: Dict[str, Any], api_key: str) -> str:
    """Yêu cầu AI phân tích các chỉ số NPV, IRR, PP, DPP."""
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'
        
        # Chuyển đổi chỉ số thành chuỗi thân thiện với AI
        wacc_percent = f"{analysis_data['WACC'] * 100:.2f}%"
        irr_percent = f"{analysis_data['IRR'] * 100:.2f}%"
        npv_value = f"{analysis_data['NPV']:,.0f}"
        
        prompt = f"""
        Bạn là một Chuyên gia Thẩm định Dự án Kinh doanh. Dưới đây là các chỉ số hiệu quả tài chính của một dự án đầu tư có vòng đời {analysis_data['N']} năm.
        
        Thông số:
        - WACC (Chi phí vốn): {wacc_percent}
        - NPV (Giá trị hiện tại thuần): {npv_value} VND
        - IRR (Tỷ suất hoàn vốn nội bộ): {irr_percent}
        - PP (Thời gian hoàn vốn tĩnh): {analysis_data['PP']:.2f} năm
        - DPP (Thời gian hoàn vốn chiết khấu): {analysis_data['DPP']:.2f} năm
        
        Hãy phân tích các chỉ số trên và đưa ra nhận xét chuyên sâu, kết luận về tính khả thi của dự án.
        1. Đánh giá NPV: Dự án có tạo ra giá trị gia tăng không?
        2. Đánh giá IRR so với WACC: Dự án có hiệu quả hơn chi phí vốn không?
        3. Đánh giá PP và DPP: Dự án có rủi ro về thanh khoản không?
        4. Kết luận cuối cùng: Khuyến nghị chấp nhận hay từ chối đầu tư.
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: {e}. Vui lòng kiểm tra Khóa API hoặc giới hạn sử dụng."
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định trong quá trình phân tích AI: {e}"


# --- Chức năng 1: Tải File và Lọc Dữ liệu ---
st.subheader("1. Tải lên và Lọc Dữ liệu Dự án")
uploaded_file = st.file_uploader(
    "Tải file Word (.docx) chứa Phương án Kinh doanh",
    type=['docx']
)

if uploaded_file and GEMINI_API_KEY:
    # Nút bấm để thực hiện thao tác lọc dữ liệu
    if st.button("🔍 Lọc Dữ liệu Tài chính bằng AI"):
        st.session_state.extraction_data = None
        st.session_state.analysis_results = None
        
        with st.spinner('Đang trích xuất văn bản và gửi đến Gemini AI...'):
            # Đọc file buffer để truyền vào hàm
            file_buffer = uploaded_file.read()
            # Thực hiện trích xuất
            data = extract_financial_data(file_buffer, GEMINI_API_KEY)

        if data:
            st.success("✅ Trích xuất dữ liệu thành công!")
            st.session_state.extraction_data = data
            
            st.markdown("##### 📌 Các Thông số Dự án đã được AI Lọc:")
            
            data_display = pd.DataFrame({
                "Chỉ tiêu": [
                    "Vốn đầu tư ban đầu ($I_0$)", 
                    "Vòng đời dự án (Năm)", 
                    "Doanh thu hàng năm ($R$)", 
                    "Chi phí hàng năm ($C$)", 
                    "WACC", 
                    "Thuế suất ($\\tau$)"
                ],
                "Giá trị": [
                    f"{data['vốn_đầu_tư']:,.0f}", 
                    f"{data['vòng_đời_dự_án']}", 
                    f"{data['doanh_thu_hàng_năm']:,.0f}", 
                    f"{data['chi_phí_hàng_năm']:,.0f}", 
                    f"{data['wacc'] * 100:.2f}%", 
                    f"{data['thuế_suất'] * 100:.2f}%"
                ]
            })
            st.dataframe(data_display, hide_index=True, use_container_width=True)


# --- Chức năng 2 & 3: Bảng Dòng Tiền và Chỉ số Đánh giá ---
if 'extraction_data' in st.session_state and st.session_state.extraction_data is not None:
    data = st.session_state.extraction_data
    
    try:
        # Tính toán tất cả các chỉ số và bảng dòng tiền
        results = calculate_financial_metrics(data)
        st.session_state.analysis_results = results
        
        # 2. Xây dựng bảng dòng tiền
        st.subheader("2. Bảng Dòng Tiền (Cash Flow Table)")
        
        # Hiển thị bảng dòng tiền
        st.dataframe(results['df_cf'].style.format({
            'Dòng tiền (CF)': '{:,.0f}',
            'Hệ số chiết khấu': '{:.4f}',
            'Dòng tiền chiết khấu (DCF)': '{:,.0f}',
            'Dòng tiền tích lũy (CCF)': '{:,.0f}',
            'Dòng tiền chiết khấu tích lũy (CDCF)': '{:,.0f}',
        }), hide_index=True, use_container_width=True)
        
        
        # 3. Tính toán các chỉ số đánh giá hiệu quả dự án
        st.subheader("3. Các Chỉ số Đánh giá Hiệu quả Dự án")
        
        col_npv, col_irr, col_pp, col_dpp = st.columns(4)
        
        with col_npv:
            # Màu sắc dựa trên NPV (NPV > 0 -> success, NPV < 0 -> error)
            npv_status = "success" if results['NPV'] > 0 else "error"
            st.metric(
                label="Giá trị Hiện tại Thuần (NPV)",
                value=f"{results['NPV']:,.0f} VND",
                delta="Khả thi" if results['NPV'] > 0 else "Không khả thi"
            )
        
        with col_irr:
            # Màu sắc dựa trên IRR so với WACC
            irr_status = "success" if results['IRR'] > results['WACC'] else "error"
            st.metric(
                label="Tỷ suất Hoàn vốn Nội bộ (IRR)",
                value=f"{results['IRR'] * 100:.2f}%",
                delta_color=irr_status,
                delta=f"WACC: {results['WACC'] * 100:.2f}%"
            )

        # Xử lý trường hợp hoàn vốn vô hạn (Inf)
        pp_display = "Không hoàn vốn" if results['PP'] == float('inf') else f"{results['PP']:.2f} năm"
        dpp_display = "Không hoàn vốn" if results['DPP'] == float('inf') else f"{results['DPP']:.2f} năm"

        with col_pp:
            st.metric(label="Thời gian Hoàn vốn Tĩnh (PP)", value=pp_display)
        with col_dpp:
            st.metric(label="Thời gian Hoàn vốn Chiết khấu (DPP)", value=dpp_display)

    except Exception as e:
        st.error(f"Lỗi khi tính toán chỉ số tài chính: {e}")
        st.info("Vui lòng kiểm tra lại dữ liệu đã được AI trích xuất (ví dụ: WACC, Thuế suất có phải là số thập phân không).")


# --- Chức năng 4: Phân tích các chỉ số hiệu quả dự án ---
if 'analysis_results' in st.session_state and st.session_state.analysis_results is not None:
    
    st.markdown("---")
    st.subheader("4. Phân tích Chuyên sâu về Hiệu quả Dự án (AI)")
    
    if st.button("🤖 Yêu cầu AI Phân tích Chỉ số Hiệu quả"):
        
        with st.spinner('Đang gửi các chỉ số đến Gemini để nhận nhận xét...'):
            ai_analysis = get_ai_analysis_metrics(st.session_state.analysis_results, GEMINI_API_KEY)
            
            st.markdown("#### **Kết quả Phân tích từ Chuyên gia Tài chính AI:**")
            st.info(ai_analysis)

elif not GEMINI_API_KEY:
    st.error("Lỗi: Không tìm thấy Khóa API. Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets.")

elif uploaded_file is None:
    st.info("Vui lòng tải lên file Word và nhấn nút 'Lọc Dữ liệu Tài chính bằng AI' để bắt đầu phân tích.")
