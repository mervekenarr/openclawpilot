#!/bin/bash
# Streamlit ve LinkedIn API'yi birlikte başlatır
python linkedin_api.py &
streamlit run dashboard.py --server.port=8501 --server.address=0.0.0.0
