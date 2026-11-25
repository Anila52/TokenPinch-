import os

def helper(x):
    return x + 1

def target(n):
    """adds one then doubles"""
    return helper(n) * 2

class Box:
    def method(self, n):
        return helper(n)

def unused(z):
    return z * 9
