# 报告与技术文档

正式技术文档以比赛提交版为准：

- `adas_technical_document.docx`：可编辑源文件；
- `adas_technical_document.pdf`：由上述 DOCX 导出的 21 页 PDF。

`adas_report.md` 是补充设计报告源文件；`adas_report_final.pdf` 是早期自动
生成的补充版本，不包含最新技术文档的表 12、参考文献和硬件实拍图。对外
提交时优先使用 `adas_technical_document.pdf`。

如果继续维护 Markdown 设计报告，可按以下命令重新生成：

```bash
py -3 stage4/tools/render_report_pdf.py \
  --output docs/report/adas_report_final.pdf
```

Before submission, verify that the report uses the current 45-test count,
PL-gray benchmark, lane feature evidence and final performance tables.
