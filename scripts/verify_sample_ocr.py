"""Reproducible offline scan diagnostics without reference-answer hints."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf
from htr.local_document import LocalDocumentPipeline
from api.services.pdf_service import calculate_render_scale


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, default=Path('data/samples/std1.pdf'))
    parser.add_argument('--output', type=Path, default=Path('data/results/std1-verified'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pipeline = LocalDocumentPipeline()
    summaries = []
    with pymupdf.open(args.input) as document:
        for number, page in enumerate(document, 1):
            scale, *_ = calculate_render_scale(page.rect)
            image = args.output / f'page-{number}.png'
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(image)
            result = pipeline.recognize_path(image)
            (args.output / f'result-{number}.json').write_text(json.dumps(result.to_dict(), indent=2), encoding='utf-8')
            summaries.append({'page':number, 'lines':len(result.lines),
                              'review_lines':len(result.metadata['quality_warnings']),
                              'foreground':result.metadata['foreground']})
            print(summaries[-1], flush=True)
    report = {'input':str(args.input), 'pages':summaries,
              'note':'Review counts are not an accuracy estimate. No written-answer ground truth is supplied.'}
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
