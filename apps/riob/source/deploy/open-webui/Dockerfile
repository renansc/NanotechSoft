ARG OPEN_WEBUI_BASE_IMAGE=ghcr.io/open-webui/open-webui:v0.9.6
FROM ${OPEN_WEBUI_BASE_IMAGE}

ARG OPEN_WEBUI_NUMPY_VERSION=2.2.6

# NumPy 2.4 exige x86-64-v2; a versao 2.2.6 mantem compatibilidade com CPUs antigas.
RUN pip install --no-cache-dir --force-reinstall "numpy==${OPEN_WEBUI_NUMPY_VERSION}" \
    && python -c "import chromadb, numpy; print('Open WebUI NumPy:', numpy.__version__)"
