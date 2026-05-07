import 'package:flutter/material.dart';

/// User widget.
class UserWidget extends StatelessWidget {
  final String name;
  UserWidget({required this.name});

  @override
  Widget build(BuildContext context) {
    return Text(name);
  }
}

class CounterState extends State<Counter> {
  int count = 0;
  void increment() { setState(() { count++; }); }
}

mixin Logging {
  void log(String msg) {}
}

enum Status { active, inactive }

extension StringX on String {
  String reversed() => "";
}

int helper() => 42;
