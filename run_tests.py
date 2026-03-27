#!/usr/bin/env python3
"""
Test runner script for Agent GW
"""

import subprocess
import sys
import argparse

def run_tests(test_type='all', verbose=False, coverage=False):
    """Run test suite"""
    
    cmd = ['python', '-m', 'pytest']
    
    # Add verbosity
    if verbose:
        cmd.append('-v')
    
    # Add coverage
    if coverage:
        cmd.extend(['--cov=.', '--cov-report=html', '--cov-report=term'])
    
    # Select tests
    if test_type == 'unit':
        cmd.extend(['tests/test_models.py', 'tests/test_arf_api.py', 
                    'tests/test_acf_server.py', 'tests/test_moqt_relay.py'])
    elif test_type == 'integration':
        cmd.append('tests/test_integration.py')
    elif test_type == 'models':
        cmd.append('tests/test_models.py')
    elif test_type == 'arf':
        cmd.append('tests/test_arf_api.py')
    elif test_type == 'acf':
        cmd.append('tests/test_acf_server.py')
    elif test_type == 'moqt':
        cmd.append('tests/test_moqt_relay.py')
    else:  # all
        cmd.append('tests/')
    
    # Run tests
    print(f"Running tests: {' '.join(cmd)}")
    print("=" * 60)
    
    result = subprocess.run(cmd)
    
    return result.returncode

def main():
    parser = argparse.ArgumentParser(description='Run Agent GW tests')
    parser.add_argument(
        'type',
        nargs='?',
        default='all',
        choices=['all', 'unit', 'integration', 'models', 'arf', 'acf', 'moqt'],
        help='Type of tests to run'
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('-c', '--coverage', action='store_true', help='Generate coverage report')
    
    args = parser.parse_args()
    
    exit_code = run_tests(args.type, args.verbose, args.coverage)
    sys.exit(exit_code)

if __name__ == '__main__':
    main()
