# Report Export

The report source is `adas_report.md`. The only tracked PDF is
`adas_report_final.pdf`.

Regenerate it after changing the Markdown:

```bash
py -3 stage4/tools/render_report_pdf.py \
  --output docs/report/adas_report_final.pdf
```

Before submission, verify that the report uses the current 45-test count,
PL-gray benchmark, lane feature evidence and final performance tables.
