#!/usr/bin/env python3
"""
Bloat Analyzer - Combined coverage and vulture analysis for dead code detection

This module integrates:
1. Coverage.py for dynamic analysis (code executed during tests)
2. Vulture for static analysis (dead/unused code detection)
3. Correlation logic to identify true bloatware
"""

import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Any
import logging

logger = logging.getLogger(__name__)


class CoverageAnalyzer:
    """Analyze test coverage to identify unexecuted code."""
    
    def __init__(self, source_dir: str = "src", test_dir: str = "tests"):
        self.source_dir = Path(source_dir)
        self.test_dir = Path(test_dir)
        self.coverage_data = {}
        
    def run_coverage(self) -> bool:
        """Run pytest with coverage and generate XML report."""
        try:
            # Run tests with coverage
            cmd = [
                "coverage", "run", "--branch", 
                "--source", str(self.source_dir),
                "-m", "pytest",
                str(self.test_dir),
                "-v"
            ]
            
            logger.info(f"Running coverage: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode not in (0, 1):  # 0=success, 1=tests failed
                logger.error(f"Coverage run failed: {result.stderr}")
                return False
            
            # Generate XML report
            xml_cmd = ["coverage", "xml", "-o", "coverage.xml"]
            subprocess.run(xml_cmd, capture_output=True, text=True, timeout=60)
            
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Coverage analysis timed out")
            return False
        except Exception as e:
            logger.error(f"Coverage analysis failed: {e}")
            return False
    
    def parse_coverage_xml(self) -> Dict[str, Any]:
        """Parse coverage.xml to get uncovered lines."""
        if not Path("coverage.xml").exists():
            return {}
        
        try:
            tree = ET.parse("coverage.xml")
            root = tree.getroot()
            
            uncovered_data = {}
            
            for package in root.findall(".//package"):
                package_name = package.get("name", "")
                
                for class_elem in package.findall(".//class"):
                    class_name = class_elem.get("name", "")
                    filename = class_elem.get("filename", "")
                    
                    if not filename.startswith(str(self.source_dir)):
                        continue
                    
                    # Get uncovered lines
                    lines = class_elem.findall(".//line")
                    uncovered_lines = []
                    
                    for line in lines:
                        if line.get("hits") == "0":
                            uncovered_lines.append(int(line.get("number")))
                    
                    if uncovered_lines:
                        full_path = str(self.source_dir / filename)
                        uncovered_data[full_path] = {
                            "package": package_name,
                            "class": class_name,
                            "uncovered_lines": uncovered_lines,
                            "total_lines": len(lines)
                        }
            
            return uncovered_data
            
        except Exception as e:
            logger.error(f"Failed to parse coverage XML: {e}")
            return {}


class VultureAnalyzer:
    """Analyze code with vulture to find dead/unused code."""
    
    def __init__(self, min_confidence: int = 80, exclude_patterns: List[str] = None):
        self.min_confidence = min_confidence
        self.exclude_patterns = exclude_patterns or [
            "**/__pycache__/**",
            "**/.git/**",
            "**/.venv/**",
            "**/venv/**",
            "**/dist/**",
            "**/build/**",
            "**/legacy/**",
            "**/compatibility/**"
        ]
    
    def run_vulture(self, target_dirs: List[str]) -> List[Dict[str, Any]]:
        """Run vulture analysis on target directories."""
        try:
            cmd = ["vulture", *target_dirs, "--min-confidence", str(self.min_confidence)]
            
            if self.exclude_patterns:
                cmd.extend(["--exclude", ",".join(self.exclude_patterns)])
            
            logger.info(f"Running vulture: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            findings = []
            
            # Parse vulture output
            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                    
                # Vulture format: filename:line: confidence%: message
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    filename, line_num, confidence_msg, message = parts
                    try:
                        confidence = int(confidence_msg.strip().rstrip("%"))
                        findings.append({
                            "file": filename.strip(),
                            "line": int(line_num.strip()),
                            "confidence": confidence,
                            "message": message.strip(),
                            "type": self._classify_finding(message)
                        })
                    except ValueError:
                        continue
            
            return findings
            
        except subprocess.TimeoutExpired:
            logger.error("Vulture analysis timed out")
            return []
        except Exception as e:
            logger.error(f"Vulture analysis failed: {e}")
            return []
    
    def _classify_finding(self, message: str) -> str:
        """Classify vulture finding by type."""
        message_lower = message.lower()
        
        if "unused function" in message_lower:
            return "unused_function"
        elif "unused class" in message_lower:
            return "unused_class"
        elif "unused import" in message_lower:
            return "unused_import"
        elif "unused variable" in message_lower:
            return "unused_variable"
        elif "unused attribute" in message_lower:
            return "unused_attribute"
        else:
            return "other"


class BloatCorrelator:
    """Correlate coverage and vulture findings to identify true bloatware."""
    
    def __init__(self, coverage_data: Dict[str, Any], vulture_findings: List[Dict[str, Any]]):
        self.coverage_data = coverage_data
        self.vulture_findings = vulture_findings
    
    def correlate_findings(self) -> Dict[str, Any]:
        """Correlate coverage and vulture findings."""
        correlated = {
            "high_confidence_bloat": [],
            "medium_confidence_bloat": [],
            "low_confidence_bloat": [],
            "summary": {
                "total_files_analyzed": 0,
                "uncovered_lines": 0,
                "vulture_findings": len(self.vulture_findings),
                "correlated_findings": 0
            }
        }
        
        # Group vulture findings by file
        vulture_by_file = {}
        for finding in self.vulture_findings:
            file_path = finding["file"]
            if file_path not in vulture_by_file:
                vulture_by_file[file_path] = []
            vulture_by_file[file_path].append(finding)
        
        # Check each file with coverage data
        for file_path, coverage_info in self.coverage_data.items():
            uncovered_lines = set(coverage_info["uncovered_lines"])
            vulture_findings = vulture_by_file.get(file_path, [])
            
            for finding in vulture_findings:
                # Check if vulture finding is on an uncovered line
                if finding["line"] in uncovered_lines:
                    confidence_score = self._calculate_confidence(finding, uncovered_lines)
                    
                    bloat_entry = {
                        "file": file_path,
                        "line": finding["line"],
                        "confidence": finding["confidence"],
                        "type": finding["type"],
                        "message": finding["message"],
                        "coverage_confidence": confidence_score,
                        "total_confidence": (finding["confidence"] + confidence_score) / 2
                    }
                    
                    # Categorize by total confidence
                    total_conf = bloat_entry["total_confidence"]
                    if total_conf >= 80:
                        correlated["high_confidence_bloat"].append(bloat_entry)
                    elif total_conf >= 60:
                        correlated["medium_confidence_bloat"].append(bloat_entry)
                    else:
                        correlated["low_confidence_bloat"].append(bloat_entry)
                    
                    correlated["summary"]["correlated_findings"] += 1
        
        correlated["summary"]["total_files_analyzed"] = len(self.coverage_data)
        correlated["summary"]["uncovered_lines"] = sum(
            len(info["uncovered_lines"]) for info in self.coverage_data.values()
        )
        
        return correlated
    
    def _calculate_confidence(self, finding: Dict[str, Any], uncovered_lines: Set[int]) -> float:
        """Calculate confidence based on surrounding uncovered lines."""
        line_num = finding["line"]
        
        # Check if surrounding lines are also uncovered
        surrounding_uncovered = 0
        check_range = 5  # Check 5 lines before and after
        
        for i in range(line_num - check_range, line_num + check_range + 1):
            if i in uncovered_lines:
                surrounding_uncovered += 1
        
        # Calculate percentage of surrounding lines that are uncovered
        total_surrounding = (check_range * 2) + 1
        return (surrounding_uncovered / total_surrounding) * 100


class BloatAnalyzer:
    """Main orchestrator for bloat analysis."""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.source_dir = self.config.get("source_dir", "src")
        self.test_dir = self.config.get("test_dir", "tests")
        self.vulture_min_confidence = self.config.get("vulture_min_confidence", 80)
        self.vulture_exclude = self.config.get("vulture_exclude", [])
        self.output_dir = Path(self.config.get("output_dir", "/app/reports/bloat"))
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize analyzers
        self.coverage_analyzer = CoverageAnalyzer(self.source_dir, self.test_dir)
        self.vulture_analyzer = VultureAnalyzer(
            min_confidence=self.vulture_min_confidence,
            exclude_patterns=self.vulture_exclude
        )
    
    def run_analysis(self) -> Dict[str, Any]:
        """Run complete bloat analysis."""
        logger.info("Starting bloat analysis...")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Step 1: Run coverage analysis
        logger.info("Running coverage analysis...")
        if not self.coverage_analyzer.run_coverage():
            logger.error("Coverage analysis failed")
            return {"error": "Coverage analysis failed"}
        
        coverage_data = self.coverage_analyzer.parse_coverage_xml()
        logger.info(f"Coverage analysis complete: {len(coverage_data)} files with uncovered lines")
        
        # Step 2: Run vulture analysis
        logger.info("Running vulture analysis...")
        vulture_findings = self.vulture_analyzer.run_vulture([self.source_dir])
        logger.info(f"Vulture analysis complete: {len(vulture_findings)} findings")
        
        # Step 3: Correlate findings
        logger.info("Correlating findings...")
        correlator = BloatCorrelator(coverage_data, vulture_findings)
        correlated_results = correlator.correlate_findings()
        
        # Step 4: Generate reports
        logger.info("Generating reports...")
        reports = self._generate_reports(correlated_results, timestamp)
        
        # Step 5: Clean up temporary files
        self._cleanup()
        
        logger.info("Bloat analysis complete")
        
        return {
            "timestamp": timestamp,
            "coverage_files_analyzed": len(coverage_data),
            "vulture_findings": len(vulture_findings),
            "correlated_findings": correlated_results["summary"]["correlated_findings"],
            "reports": reports,
            "results": correlated_results
        }
    
    def _generate_reports(self, results: Dict[str, Any], timestamp: str) -> Dict[str, str]:
        """Generate various report formats."""
        reports = {}
        
        # JSON report
        json_report = self.output_dir / f"bloat_report_{timestamp}.json"
        with open(json_report, "w") as f:
            json.dump(results, f, indent=2)
        reports["json"] = str(json_report)
        
        # Text summary
        text_report = self.output_dir / f"bloat_summary_{timestamp}.txt"
        with open(text_report, "w") as f:
            f.write(self._generate_text_summary(results))
        reports["text"] = str(text_report)
        
        # HTML report
        html_report = self.output_dir / f"bloat_report_{timestamp}.html"
        with open(html_report, "w") as f:
            f.write(self._generate_html_report(results, timestamp))
        reports["html"] = str(html_report)
        
        return reports
    
    def _generate_text_summary(self, results: Dict[str, Any]) -> str:
        """Generate text summary report."""
        summary = results["summary"]
        
        text = f"""BLOAT ANALYSIS REPORT
=====================

Summary:
--------
Total files analyzed: {summary['total_files_analyzed']}
Uncovered lines: {summary['uncovered_lines']}
Vulture findings: {summary['vulture_findings']}
Correlated findings: {summary['correlated_findings']}

High Confidence Bloat ({len(results['high_confidence_bloat'])}):
-------------------------"""
        
        for item in results["high_confidence_bloat"]:
            text += f"\n- {item['file']}:{item['line']} - {item['type']} ({item['total_confidence']:.1f}%)"
            text += f"\n  {item['message']}"
        
        text += f"\n\nMedium Confidence Bloat ({len(results['medium_confidence_bloat'])}):"
        text += f"\n---------------------------"
        
        for item in results["medium_confidence_bloat"]:
            text += f"\n- {item['file']}:{item['line']} - {item['type']} ({item['total_confidence']:.1f}%)"
        
        text += f"\n\nLow Confidence Bloat ({len(results['low_confidence_bloat'])}):"
        text += f"\n------------------------"
        
        for item in results["low_confidence_bloat"]:
            text += f"\n- {item['file']}:{item['line']} - {item['type']} ({item['total_confidence']:.1f}%)"
        
        return text
    
    def _generate_html_report(self, results: Dict[str, Any], timestamp: str) -> str:
        """Generate HTML report."""
        summary = results["summary"]
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Bloat Analysis Report - {timestamp}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; }}
        .section {{ margin: 20px 0; }}
        .finding {{ margin: 10px 0; padding: 10px; border-left: 4px solid; }}
        .high {{ border-color: #dc3545; background: #f8d7da; }}
        .medium {{ border-color: #ffc107; background: #fff3cd; }}
        .low {{ border-color: #6c757d; background: #f8f9fa; }}
        .confidence {{ font-weight: bold; }}
    </style>
</head>
<body>
    <h1>Bloat Analysis Report</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="summary">
        <h2>Summary</h2>
        <p>Total files analyzed: {summary['total_files_analyzed']}</p>
        <p>Uncovered lines: {summary['uncovered_lines']}</p>
        <p>Vulture findings: {summary['vulture_findings']}</p>
        <p>Correlated findings: {summary['correlated_findings']}</p>
    </div>
    
    <div class="section">
        <h2>High Confidence Bloat ({len(results['high_confidence_bloat'])})</h2>"""
        
        for item in results["high_confidence_bloat"]:
            html += f"""
        <div class="finding high">
            <div class="confidence">Confidence: {item['total_confidence']:.1f}%</div>
            <div><strong>{item['file']}:{item['line']}</strong> - {item['type']}</div>
            <div>{item['message']}</div>
        </div>"""
        
        html += f"""
    </div>
    
    <div class="section">
        <h2>Medium Confidence Bloat ({len(results['medium_confidence_bloat'])})</h2>"""
        
        for item in results["medium_confidence_bloat"]:
            html += f"""
        <div class="finding medium">
            <div class="confidence">Confidence: {item['total_confidence']:.1f}%</div>
            <div><strong>{item['file']}:{item['line']}</strong> - {item['type']}</div>
        </div>"""
        
        html += f"""
    </div>
    
    <div class="section">
        <h2>Low Confidence Bloat ({len(results['low_confidence_bloat'])})</h2>"""
        
        for item in results["low_confidence_bloat"]:
            html += f"""
        <div class="finding low">
            <div class="confidence">Confidence: {item['total_confidence']:.1f}%</div>
            <div><strong>{item['file']}:{item['line']}</strong> - {item['type']}</div>
            <div>{item['message']}</div>
        </div>"""

        html += """
    </div>
</body>
</html>"""

        return html
