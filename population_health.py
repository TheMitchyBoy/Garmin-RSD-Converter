#!/usr/bin/env python3
"""
Population health analytics for sonar-detected fish.
Analyzes fish population metrics, trends, and health indicators.
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
from collections import defaultdict
import statistics

from sonar_schema import HEURISTIC_DISCLAIMER

logger = logging.getLogger(__name__)


class PopulationHealthAnalytics:
    """Analyze heuristic population metrics from sonar intensity detections."""

    DISCLAIMER = HEURISTIC_DISCLAIMER
    
    @staticmethod
    def analyze_population_metrics(
        detections_file: Path,
        output_file: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Calculate population health metrics from fish detections.
        
        Args:
            detections_file: GeoJSON file from fish_detection.py
            output_file: Output JSON report
        
        Returns:
            Dictionary with health metrics
        """
        if output_file is None:
            output_file = Path(str(detections_file).replace('_fish_detections', '_population_report'))
            output_file = output_file.with_suffix('.json')
        
        logger.info("Analyzing population health metrics...")
        
        try:
            with open(detections_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            features = data.get('features', [])
            
            if not features:
                logger.warning("No fish detections found")
                return {'error': 'No detections'}
            
            # Extract data from features
            intensities = []
            depths = []
            sizes = defaultdict(int)
            confidences = []
            coordinates = []
            
            for feature in features:
                props = feature.get('properties', {})
                coords = feature.get('geometry', {}).get('coordinates', [])
                
                intensities.append(props.get('intensity', 0))
                depths.append(props.get('depth_m', 0))
                sizes[props.get('size', 'unknown')] += 1
                confidences.append(props.get('confidence', 0))
                coordinates.append(tuple(coords))  # Make hashable
            
            # Calculate metrics
            total_detections = len(features)
            unique_locations = len(set(coordinates))  # Unique coordinate tuples
            
            metrics = {
                'timestamp': datetime.now().isoformat(),
                'total_detections': total_detections,
                'population_health': {
                    'density_metric': total_detections / max(1, unique_locations),
                    'average_intensity': statistics.mean(intensities) if intensities else 0,
                    'intensity_std_dev': statistics.stdev(intensities) if len(intensities) > 1 else 0,
                    'average_depth': statistics.mean(depths) if depths else 0,
                    'average_confidence': statistics.mean(confidences) if confidences else 0,
                },
                'population_composition': {
                    'small': sizes.get('small', 0),
                    'medium': sizes.get('medium', 0),
                    'large': sizes.get('large', 0),
                    'school': sizes.get('school', 0),
                    'school_percentage': (sizes.get('school', 0) / total_detections * 100) if total_detections > 0 else 0,
                },
                'depth_distribution': {
                    'min_depth_m': min(depths) if depths else 0,
                    'max_depth_m': max(depths) if depths else 0,
                    'median_depth_m': statistics.median(depths) if depths else 0,
                },
                'health_indicators': PopulationHealthAnalytics._calculate_health_indicators(
                    intensities, sizes, total_detections
                ),
            }
            
            # Save report
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(metrics, f, indent=2)
            
            logger.info(f"Population report generated: {output_file}")
            logger.info(f"  Total fish detected: {total_detections}")
            logger.info(f"  School ratio: {metrics['population_composition']['school_percentage']:.1f}%")
            
            return metrics
        
        except Exception as e:
            logger.error(f"Error analyzing population: {e}")
            raise
    
    @staticmethod
    def _calculate_health_indicators(
        intensities: List[float],
        sizes: Dict[str, int],
        total: int
    ) -> Dict[str, Any]:
        """Calculate health score indicators (0-100)"""
        
        indicators = {}
        
        # Diversity score: is there a good mix of fish sizes?
        # Schools are good (indicate schooling behavior = health)
        school_ratio = sizes.get('school', 0) / max(1, total)
        diversity_score = min(100, school_ratio * 100 + (1 - school_ratio) * 50)
        indicators['diversity_score'] = round(diversity_score, 1)
        indicators['diversity_status'] = (
            'Excellent' if diversity_score > 80 else
            'Good' if diversity_score > 60 else
            'Fair' if diversity_score > 40 else
            'Poor'
        )
        
        # Activity score: are fish showing strong acoustic signatures?
        avg_intensity = statistics.mean(intensities) if intensities else 0
        activity_score = min(100, (avg_intensity / 100) * 100)
        indicators['activity_score'] = round(activity_score, 1)
        indicators['activity_status'] = (
            'Very Active' if activity_score > 80 else
            'Active' if activity_score > 60 else
            'Moderate' if activity_score > 40 else
            'Low'
        )
        
        # Population abundance score
        # Based on detection density
        abundance_score = min(100, max(0, (total - 10) / 100 * 100))
        indicators['abundance_score'] = round(abundance_score, 1)
        indicators['abundance_status'] = (
            'Abundant' if abundance_score > 70 else
            'Good' if abundance_score > 50 else
            'Moderate' if abundance_score > 30 else
            'Sparse'
        )
        
        # Overall health score
        overall_health = (diversity_score + activity_score + abundance_score) / 3
        indicators['overall_health_score'] = round(overall_health, 1)
        indicators['overall_status'] = (
            'Excellent' if overall_health > 75 else
            'Good' if overall_health > 60 else
            'Fair' if overall_health > 45 else
            'Poor'
        )
        
        return indicators
    
    @staticmethod
    def generate_public_report(
        population_metrics: Dict[str, Any],
        location_name: str = "Fishing Area",
        output_file: Optional[Path] = None
    ) -> Path:
        """
        Generate a public-friendly report about fishing health.
        
        Args:
            population_metrics: Dict from analyze_population_metrics
            location_name: Name of the surveyed location
            output_file: Output markdown/html file
        
        Returns:
            Path to generated report
        """
        if output_file is None:
            output_file = Path(f"fishing_health_report_{datetime.now().strftime('%Y%m%d')}.md")
        
        logger.info(f"Generating public report: {output_file}")
        
        try:
            # Generate markdown report
            health = population_metrics.get('health_indicators', {})
            pop = population_metrics.get('population_composition', {})
            
            report = f"""# Sonar Survey Heuristic Report

> **Disclaimer:** {PopulationHealthAnalytics.DISCLAIMER}
> Scores below are composite heuristics derived from sonar intensity patterns,
> not biological survey or fisheries assessment data.

## {location_name}
**Report Date:** {population_metrics.get('timestamp', 'Unknown')}

---

## Composite Heuristic Score

**Status:** {health.get('overall_status', 'Unknown')}  
**Score:** {health.get('overall_health_score', 'N/A')}/100

---

## Key Findings

### Detection Density
- **Status:** {health.get('abundance_status', 'Unknown')}
- **Abundance Score:** {health.get('abundance_score', 'N/A')}/100
- **Intensity Signatures Detected:** {population_metrics.get('total_detections', 0):,}

### Intensity Activity
- **Status:** {health.get('activity_status', 'Unknown')}
- **Activity Score:** {health.get('activity_score', 'N/A')}/100
- **Average Intensity:** {population_metrics.get('population_health', {}).get('average_intensity', 'N/A')}

### Signature Diversity
- **Status:** {health.get('diversity_status', 'Unknown')}
- **Diversity Score:** {health.get('diversity_score', 'N/A')}/100
- **High-intensity clusters:** {pop.get('school', 0)} ({pop.get('school_percentage', 0):.1f}%)

---

## Signature Breakdown

| Size Category | Count | Percentage |
|---|---|---|
| Small signatures | {pop.get('small', 0)} | {pop.get('small', 0)/population_metrics.get('total_detections', 1)*100:.1f}% |
| Medium signatures | {pop.get('medium', 0)} | {pop.get('medium', 0)/population_metrics.get('total_detections', 1)*100:.1f}% |
| Large signatures | {pop.get('large', 0)} | {pop.get('large', 0)/population_metrics.get('total_detections', 1)*100:.1f}% |
| High-intensity clusters | {pop.get('school', 0)} | {pop.get('school_percentage', 0):.1f}% |

---

## Habitat Conditions

### Depth Profile
- **Minimum Depth:** {population_metrics.get('depth_distribution', {}).get('min_depth_m', 'N/A')} m
- **Maximum Depth:** {population_metrics.get('depth_distribution', {}).get('max_depth_m', 'N/A')} m
- **Average Depth:** {population_metrics.get('population_health', {}).get('average_depth', 'N/A')} m
- **Median Depth:** {population_metrics.get('depth_distribution', {}).get('median_depth_m', 'N/A')} m

---

## Health Assessment

### Interpretation

These scores summarize sonar intensity patterns only. They should not be used as
biological population assessments or fisheries management decisions without
independent validation.

"""
            
            # Add interpretation based on health scores
            overall_status = health.get('overall_status', 'Unknown')
            
            if overall_status == 'Excellent':
                report += """**The survey area shows a high density of strong intensity signatures.**

Observed patterns include:
- Many detections across the track
- Diverse intensity categories
- Elevated average intensity readings
- Depth readings within the configured detection window

**Recommendation:** Use these results as exploratory sonar analysis only.
Validate with independent survey methods before drawing biological conclusions.
"""
            elif overall_status == 'Good':
                report += """**The survey area shows moderate-to-strong intensity signature activity.**

Observed patterns include:
- Stable detection counts
- Reasonable category diversity
- Moderate intensity levels

**Recommendation:** Continue monitoring with consistent survey parameters.
"""
            elif overall_status == 'Fair':
                report += """**The survey area shows limited intensity signature activity.**

Observed patterns include:
- Moderate detection counts
- Limited category diversity
- Variable intensity levels

**Recommendation:** Review sonar settings and survey coverage before interpreting results.
"""
            else:
                report += """**The survey area shows sparse intensity signature activity.**

Observed patterns include:
- Few detections
- Limited diversity
- Low average intensity

**Recommendation:** Treat results as low-confidence exploratory data.
"""
            
            report += f"""

---

## Methodology

This report is based on heuristic sonar intensity analysis:
- Intensity-threshold signature classification
- Detection aggregation metrics
- Depth distribution summaries
- Composite heuristic scoring

**Data Quality:** Average detection confidence = {population_metrics.get('population_health', {}).get('average_confidence', 'N/A')}

**Important:** {PopulationHealthAnalytics.DISCLAIMER}

---

**Generated by:** Garmin Sonar Converter  
**Report Version:** 1.1

"""
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            
            logger.info(f"Public report generated: {output_file}")
            return output_file
        
        except Exception as e:
            logger.error(f"Error generating report: {e}")
            raise
