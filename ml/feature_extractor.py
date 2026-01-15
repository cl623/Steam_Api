"""
Feature extraction module for parsing Steam market item names
and extracting structured features for machine learning.
"""
import re
from typing import Dict, Optional, Tuple


class ItemFeatureExtractor:
    """
    Extracts features from Steam market item names.
    
    Handles:
    - Weapon skins with conditions (Factory New, Minimal Wear, etc.)
    - Stickers
    - Crates/Cases
    - Agent skins
    - Other item types
    """
    
    # Weapon conditions in order of quality (higher = better)
    CONDITIONS = {
        'factory new': 5,
        'factory-new': 5,
        'fn': 5,
        'minimal wear': 4,
        'minimal-wear': 4,
        'mw': 4,
        'field-tested': 3,
        'field tested': 3,
        'ft': 3,
        'well-worn': 2,
        'well worn': 2,
        'ww': 2,
        'battle-scarred': 1,
        'battle scarred': 1,
        'bs': 1,
    }
    
    # Common weapon prefixes (CS2 weapons)
    WEAPON_PREFIXES = [
        'ak-47', 'm4a4', 'm4a1-s', 'm4a1s', 'awp', 'glock-18', 'glock18', 'glock',
        'usp-s', 'usps', 'usp', 'p250', 'five-seven', 'fiveseven', 'tec-9', 'tec9',
        'cz75-auto', 'cz75', 'p2000', 'p2000', 'r8 revolver', 'r8', 'deagle',
        'desert eagle', 'dual berettas', 'dual', 'p250', 'fn57', 'g3sg1', 'galil ar',
        'galil', 'm249', 'mac-10', 'mac10', 'mp5-sd', 'mp5sd', 'mp5', 'mp7', 'mp9',
        'negev', 'nova', 'p90', 'pp-bizon', 'ppbizon', 'sawed-off', 'sawedoff',
        'scar-20', 'scar20', 'sg 553', 'sg553', 'ssg 08', 'ssg08', 'xm1014',
        'm4a1', 'aug', 'famas', 'g36c', 'mag-7', 'mag7', 'ump-45', 'ump45',
        'bayonet', 'butterfly', 'flip', 'gut', 'huntsman', 'karambit', 'm9 bayonet',
        'm9', 'navaja', 'shadow daggers', 'stiletto', 'talon', 'ursus', 'falchion',
        'bowie', 'classic knife', 'paracord', 'survival', 'skeleton', 'nomad',
        'broken fang', 'driver gloves', 'hand wraps', 'moto gloves', 'specialist',
        'sport gloves', 'bloodhound', 'hydra', 'wraps', 'gloves'
    ]
    
    # Item type keywords
    TYPE_KEYWORDS = {
        'sticker': ['sticker', 'sticker capsule', 'sticker |'],
        'case': ['case', 'capsule', 'key', 'package', 'collection'],
        'agent': ['operator', 'agent', 'character', 'soldier'],
        'gloves': ['gloves', 'hand wraps', 'wraps'],
        'knife': ['knife', 'bayonet', 'karambit', 'butterfly', 'dagger'],
        'music_kit': ['music kit', 'music'],
        'graffiti': ['graffiti', 'spray'],
        'patch': ['patch'],
        'pin': ['pin'],
    }
    
    def __init__(self):
        """Initialize the feature extractor."""
        # Compile regex patterns for efficiency
        self.condition_pattern = re.compile(
            r'\(' + r'|'.join([re.escape(c) for c in self.CONDITIONS.keys()]) + r'\)',
            re.IGNORECASE
        )
        self.weapon_pattern = re.compile(
            r'^(' + '|'.join([re.escape(w) for w in self.WEAPON_PREFIXES]) + r')',
            re.IGNORECASE
        )
    
    def extract_features(self, item_name: str) -> Dict:
        """
        Extract all features from an item name.
        
        Args:
            item_name: The market hash name of the item
            
        Returns:
            Dictionary containing extracted features
        """
        item_name_lower = item_name.lower()
        
        features = {
            'item_type': self._extract_item_type(item_name),
            'is_weapon_skin': 0,
            'weapon_name': None,
            'skin_name': None,
            'condition': None,
            'condition_quality': 0,  # Numeric quality score (0-5)
            'is_stattrak': 0,
            'is_souvenir': 0,
            'has_sticker': 0,
            'is_case': 0,
            'is_sticker': 0,
            'is_agent': 0,
            'is_gloves': 0,
            'is_knife': 0,
        }
        
        # Check for StatTrak
        if 'stattrak' in item_name_lower or 'stat trak' in item_name_lower:
            features['is_stattrak'] = 1
        
        # Check for Souvenir
        if 'souvenir' in item_name_lower:
            features['is_souvenir'] = 1
        
        # Check for sticker in name
        if 'sticker' in item_name_lower:
            features['has_sticker'] = 1
        
        # Extract weapon skin features
        weapon_skin_features = self._extract_weapon_skin_features(item_name)
        if weapon_skin_features:
            features.update(weapon_skin_features)
            features['is_weapon_skin'] = 1
        
        # Set boolean flags for item types
        item_type = features['item_type']
        if item_type == 'case':
            features['is_case'] = 1
        elif item_type == 'sticker':
            features['is_sticker'] = 1
        elif item_type == 'agent':
            features['is_agent'] = 1
        elif item_type == 'gloves':
            features['is_gloves'] = 1
        elif item_type == 'knife':
            features['is_knife'] = 1
        
        return features
    
    def _extract_item_type(self, item_name: str) -> str:
        """
        Determine the item type based on keywords.
        
        Args:
            item_name: The item name
            
        Returns:
            Item type string (weapon_skin, sticker, case, agent, etc.)
        """
        item_name_lower = item_name.lower()
        
        # Check for weapon skin pattern (weapon | skin name)
        if '|' in item_name and not any(kw in item_name_lower for kw in ['sticker |', 'music']):
            # Check if it's actually a weapon skin vs agent skin
            if any(weapon in item_name_lower for weapon in self.WEAPON_PREFIXES):
                return 'weapon_skin'
            # Agent skins also use | separator
            if any(kw in item_name_lower for kw in ['operator', 'agent', 'character']):
                return 'agent'
            # Could be a weapon skin with unusual weapon name
            return 'weapon_skin'
        
        # Check other types
        for item_type, keywords in self.TYPE_KEYWORDS.items():
            if any(kw in item_name_lower for kw in keywords):
                return item_type
        
        # Default to 'other' if we can't determine
        return 'other'
    
    def _extract_weapon_skin_features(self, item_name: str) -> Optional[Dict]:
        """
        Extract weapon skin specific features.
        
        Args:
            item_name: The item name
            
        Returns:
            Dictionary with weapon_skin features or None if not a weapon skin
        """
        # Pattern: "Weapon | Skin Name (Condition)"
        # or "StatTrak™ Weapon | Skin Name (Condition)"
        # or "Souvenir Weapon | Skin Name (Condition)"
        
        if '|' not in item_name:
            return None
        
        # Remove StatTrak and Souvenir prefixes before parsing
        original_name = item_name
        item_name_clean = item_name
        
        # Remove StatTrak prefix (handle both "StatTrak™" and "StatTrak")
        if 'stattrak' in item_name.lower():
            # Remove StatTrak prefix and any special characters
            item_name_clean = re.sub(r'^[^\|]*?stattrak[™™\s]*', '', item_name_clean, flags=re.IGNORECASE)
            item_name_clean = item_name_clean.strip()
        
        # Remove Souvenir prefix
        if 'souvenir' in item_name_clean.lower():
            item_name_clean = re.sub(r'^souvenir\s+', '', item_name_clean, flags=re.IGNORECASE)
            item_name_clean = item_name_clean.strip()
        
        parts = item_name_clean.split('|')
        if len(parts) != 2:
            return None
        
        weapon_part = parts[0].strip()
        skin_part = parts[1].strip()
        
        # Extract condition from skin part
        condition = None
        condition_quality = 0
        
        # Try to find condition in parentheses
        condition_match = self.condition_pattern.search(skin_part)
        if condition_match:
            condition_text = condition_match.group(0).lower().strip('()')
            condition = condition_text
            condition_quality = self.CONDITIONS.get(condition_text, 0)
        else:
            # Check if condition is mentioned without parentheses
            for cond_key, quality in self.CONDITIONS.items():
                if cond_key in skin_part.lower():
                    condition = cond_key
                    condition_quality = quality
                    break
        
        # Extract weapon name (first word or hyphenated phrase)
        # Handle multi-word weapons like "M4A1-S", "Glock-18", etc.
        weapon_name = None
        weapon_words = weapon_part.split()
        if weapon_words:
            # Try to match known weapon prefixes
            for weapon_prefix in self.WEAPON_PREFIXES:
                if weapon_part.lower().startswith(weapon_prefix):
                    weapon_name = weapon_prefix
                    break
            
            # If no match, use first word(s) up to hyphen or first 2 words
            if not weapon_name:
                if '-' in weapon_part:
                    weapon_name = weapon_part.split('-')[0].strip().lower()
                else:
                    # Take first word, or first two words if second is short
                    if len(weapon_words) > 1 and len(weapon_words[1]) <= 3:
                        weapon_name = ' '.join(weapon_words[:2]).lower()
                    else:
                        weapon_name = weapon_words[0].lower()
        
        # Extract skin name (everything after | minus condition)
        skin_name = skin_part
        if condition_match:
            # Remove condition from skin name
            skin_name = skin_part[:condition_match.start()].strip()
            if skin_name.endswith('('):
                skin_name = skin_name[:-1].strip()
        
        return {
            'weapon_name': weapon_name,
            'skin_name': skin_name.lower() if skin_name else None,
            'condition': condition,
            'condition_quality': condition_quality,
        }
    
    def get_feature_vector(self, item_name: str) -> Dict[str, float]:
        """
        Get a feature vector suitable for machine learning.
        
        Args:
            item_name: The item name
            
        Returns:
            Dictionary of numeric and categorical features
        """
        features = self.extract_features(item_name)
        
        # Create one-hot encoded item type features
        item_type = features['item_type']
        type_features = {
            'type_weapon_skin': 1.0 if item_type == 'weapon_skin' else 0.0,
            'type_sticker': 1.0 if item_type == 'sticker' else 0.0,
            'type_case': 1.0 if item_type == 'case' else 0.0,
            'type_agent': 1.0 if item_type == 'agent' else 0.0,
            'type_gloves': 1.0 if item_type == 'gloves' else 0.0,
            'type_knife': 1.0 if item_type == 'knife' else 0.0,
            'type_other': 1.0 if item_type == 'other' else 0.0,
        }
        
        # Combine all features
        feature_vector = {
            # Item type flags
            **type_features,
            # Weapon skin features
            'is_weapon_skin': float(features['is_weapon_skin']),
            'condition_quality': float(features['condition_quality']),
            'is_stattrak': float(features['is_stattrak']),
            'is_souvenir': float(features['is_souvenir']),
            'has_sticker': float(features['has_sticker']),
            # Item type flags
            'is_case': float(features['is_case']),
            'is_sticker': float(features['is_sticker']),
            'is_agent': float(features['is_agent']),
            'is_gloves': float(features['is_gloves']),
            'is_knife': float(features['is_knife']),
        }
        
        return feature_vector


def test_extractor():
    """Test the feature extractor with sample item names."""
    extractor = ItemFeatureExtractor()
    
    test_items = [
        "AK-47 | Aquamarine Revenge (Minimal Wear)",
        "AK-47 | B the Monster (Battle-Scarred)",
        "AK-47 | Blue Laminate (Field-Tested)",
        "AK-47 | Crossfade (Factory New)",
        "2020 RMR Legends",
        "Operation Breakout Weapon Case",
        "Blueberries' Buckshot | NSWC SEAL",
        "StatTrak™ AK-47 | Redline (Field-Tested)",
        "Souvenir AWP | Dragon Lore (Factory New)",
    ]
    
    print("Testing ItemFeatureExtractor:")
    print("=" * 80)
    for item in test_items:
        features = extractor.extract_features(item)
        print(f"\nItem: {item}")
        print(f"  Type: {features['item_type']}")
        if features['is_weapon_skin']:
            print(f"  Weapon: {features['weapon_name']}")
            print(f"  Skin: {features['skin_name']}")
            print(f"  Condition: {features['condition']} (quality: {features['condition_quality']})")
        print(f"  StatTrak: {features['is_stattrak']}")
        print(f"  Souvenir: {features['is_souvenir']}")
        
        feature_vector = extractor.get_feature_vector(item)
        print(f"  Feature vector keys: {list(feature_vector.keys())}")


if __name__ == '__main__':
    test_extractor()
